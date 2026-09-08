# -*- coding: utf-8 -*-
"""
校园网助手官网 · Cloudflare Pages 一键部署脚本
================================================
第一次使用:
  1. 打开同目录的 deploy_config.json,把 api_token 换成你的 Token
     (Token 获取步骤见 chat 记录或 docs)
  2. 双击 部署.cmd,或命令行运行 python deploy_cf.py

以后每次改完内容(管理页保存 data.js 后):
  再运行一次本脚本即可,十几秒后线上生效。

原理:纯 Python 调 Cloudflare Pages 直传 API(与 wrangler 同协议):
  拿上传令牌 -> 传文件(blake3 内容哈希) -> upsert-hashes -> 创建部署
"""
import base64
import json
import mimetypes
import pathlib
import sys

import requests

BASE = pathlib.Path(__file__).resolve().parent
PACK_DIR = BASE / "线上包"          # 只含公开文件,不含 admin/server
CONFIG_PATH = BASE / "deploy_config.json"
API_ROOT = "https://api.cloudflare.com/client/v4"


class ApiError(Exception):
    pass


def die(msg):
    print("[失败] " + msg)
    sys.exit(1)


def read_config():
    if not CONFIG_PATH.exists():
        die("找不到 deploy_config.json")
    cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
    token = (cfg.get("api_token") or "").strip()
    if not token or "粘贴" in token or "在这里" in token:
        die("请先在 deploy_config.json 里填入 api_token")
    return cfg, token


def call_api(method, path, token, json_body=None, multipart=None, raw_auth=None):
    """调用 Cloudflare API(requests 通道;urllib 会被边缘拦成 405),
    成功返回 result 字段,失败抛 ApiError(中文信息)"""
    url = path if path.startswith("http") else API_ROOT + path
    headers = {"Authorization": "Bearer " + (raw_auth or token)}
    data = None
    files = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")
    elif multipart is not None:
        # 全部走 multipart:字符串字段用 (None, value) 形式,
        # 与 undici FormData.append(纯字符串字段)行为一致
        files = []
        for name, value in multipart:
            if isinstance(value, tuple):  # (filename, content, content_type)
                fn, content, ctype = value
                files.append((name, (fn, content, ctype)))
            else:
                files.append((name, (None, str(value))))
    try:
        r = requests.request(method, url, headers=headers, data=data,
                             files=files, timeout=120)
    except Exception as e:
        raise ApiError("网络请求失败: %s" % e)
    if r.status_code >= 400:
        detail = ""
        try:
            errs = r.json().get("errors") or [{}]
            detail = errs[0].get("message", "")
        except Exception:
            detail = r.text[:120]
        raise ApiError("接口返回 HTTP %s %s %s" % (r.status_code, r.reason, detail))
    try:
        js = r.json()
    except Exception:
        raise ApiError("响应不是 JSON: %s" % r.text[:120])
    if not js.get("success"):
        errs = js.get("errors") or [{}]
        raise ApiError("接口报错: %s" % (errs[0].get("message") or js))
    return js.get("result")


def cf_hash(data, rel_path):
    """与 wrangler hashFile 完全一致:
    blake3( base64(文件内容) + 扩展名不带点 ).hex() 取前 32 位。
    哈希算错不会报错,但线上会全部 404——这里绝不能改。"""
    from blake3 import blake3
    ext = pathlib.Path(rel_path).suffix.lstrip(".")
    return blake3(base64.b64encode(data) + ext.encode("ascii")).hexdigest()[:32]


def main():
    # 提前检查依赖：blake3 缺失时给出明确提示，而不是哈希计算时抛 ImportError
    try:
        import blake3  # noqa: F401
    except ImportError:
        die("缺少依赖 blake3，请先安装：pip install blake3")
    cfg, token = read_config()
    project = (cfg.get("project") or "jsu-campus-helper").strip()
    if not PACK_DIR.exists():
        die("找不到线上包目录: %s" % PACK_DIR)

    # 1) 收集要上传的文件(相对路径用 / 分隔,manifest 键带前导 /)
    files = []
    for p in sorted(PACK_DIR.rglob("*")):
        if p.is_file():
            rel = p.relative_to(PACK_DIR).as_posix()
            files.append(("/" + rel, p.read_bytes(), rel))
    if not files:
        die("线上包目录是空的,请先同步 index.html / data.js / assets")
    print("待上传 %d 个文件: %s" % (len(files), ", ".join(f[0] for f in files)))

    # 2) 确定账号 id:优先用配置里的 account_id(列表接口有时返回空),
    #    否则用 Token 自动发现
    account_id = (cfg.get("account_id") or "").strip()
    if account_id:
        print("使用配置的账号 id: %s" % account_id)
    else:
        accounts = call_api("GET", "/accounts", token)
        if not accounts:
            die("Token 查不到账号。请在 deploy_config.json 填入 account_id"
                "(控制台任意页面网址 dash.cloudflare.com/ 后面那串 32 位字符)")
        account_id = accounts[0]["id"]
        print("账号: %s" % (accounts[0].get("name") or account_id))

    # 3) 确保项目存在(404/409 都能正确处理:不存在则建,已存在直接用)
    proj = None
    try:
        proj = call_api("GET", "/accounts/%s/pages/projects/%s" % (account_id, project), token)
        print("项目已存在: %s" % project)
    except ApiError:
        print("项目不存在,自动创建: %s" % project)
        try:
            proj = call_api("POST", "/accounts/%s/pages/projects" % account_id, token,
                            json_body={"name": project, "production_branch": "main"})
        except ApiError as e2:
            if "8000002" in str(e2) or "already exists" in str(e2):
                proj = call_api("GET", "/accounts/%s/pages/projects/%s" % (account_id, project), token)
            else:
                raise
    prod_branch = (proj or {}).get("production_branch") or "main"
    print("生产分支: %s" % prod_branch)

    # 4) 计算内容哈希 + 取上传令牌
    manifest = {}
    for url_path, data, rel in files:
        manifest[url_path] = cf_hash(data, rel)
    jwt_info = call_api("GET", "/accounts/%s/pages/projects/%s/upload-token" % (account_id, project), token)
    jwt = jwt_info["jwt"]
    print("已取得上传令牌")

    # 5) 查服务端缺失的哈希(缓存命中可免传)
    all_hashes = [manifest[u] for u, _, _ in files]
    missing = call_api("POST", API_ROOT + "/pages/assets/check-missing", token,
                       json_body={"hashes": all_hashes}, raw_auth=jwt)

    # 6) 上传缺失文件(现行协议:JSON 数组,内容 base64)
    payload = [{"key": manifest[u], "value": base64.b64encode(d).decode(),
                "metadata": {"contentType": _guess_mime(rel)}, "base64": True}
               for u, d, rel in files if manifest[u] in missing]
    if payload:
        call_api("POST", API_ROOT + "/pages/assets/upload", token,
                 json_body=payload, raw_auth=jwt)
        print("已上传 %d 个文件" % len(payload))
    else:
        print("全部文件服务端已有缓存,免上传")

    # 7) 创建生产部署(分支用项目自己的生产分支)
    dep = call_api("POST", "/accounts/%s/pages/projects/%s/deployments" % (account_id, project), token,
                   multipart=[("manifest", json.dumps(manifest)), ("branch", prod_branch)])
    print("-" * 46)
    print("[成功] 已上线!")
    print("正式地址: https://%s.pages.dev" % project)
    if isinstance(dep, dict) and dep.get("url"):
        print("本次部署: %s" % dep["url"])


def _guess_mime(rel):
    # _headers / _redirects 必须用 text/plain，否则 Cloudflare 会当作普通二进制文件
    # 直接返回而不解析其中的规则
    name = pathlib.PurePosixPath(rel).name
    if name in ("_headers", "_redirects"):
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(rel)[0] or "application/octet-stream"


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        die(str(e))
