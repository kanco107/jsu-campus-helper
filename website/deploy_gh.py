# -*- coding: utf-8 -*-
"""
校园网助手官网 · 两个安装包(exe + apk)发布到 GitHub Releases
================================================
一次性前置(约 5 分钟):
  1. 注册/登录 github.com(免费,无需银行卡)
  2. 新建公开仓库: 点右上角 + -> New repository
     - 名字随意,如 campus-helper
     - 勾选 "Add a README file"(仓库不能是空的,否则建不了 Release)
  3. 生成上传令牌: 右上角头像 -> Settings -> Developer settings
     -> Personal access tokens -> Tokens (classic) -> Generate new token (classic)
     - Note: 随意,如 campus-helper-upload
     - Expiration: 选个期限(如 90 天,到期重新生成即可)
     - 权限勾选: repo(整个 repo 大项)
     - 生成后复制,只显示一次
  4. 把 "用户名/仓库名" 和 Token 填进 deploy_config.json 的 gh_repo / gh_token

之后每次更新安装包(如出了 v1.2):
  双击 上传安装包.cmd。同名附件自动覆盖,下载链接格式不变。

下载直链格式(公开仓库无需登录):
  https://github.com/<用户名>/<仓库>/releases/download/v1.1/<文件名>
"""
import json
import pathlib
import sys
import urllib.parse

import requests

from deploy_cf import CONFIG_PATH, die


def load_cfg():
    if not CONFIG_PATH.exists():
        die("找不到 deploy_config.json")
    return json.loads(CONFIG_PATH.read_text("utf-8"))


def gh(method, path, token, ok_codes=(200,), **kw):
    """调用 GitHub API;非预期状态码时中文报错退出"""
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "campus-helper-deployer",
    }
    r = requests.request(method, "https://api.github.com" + path,
                         headers=headers, timeout=60, **kw)
    if r.status_code not in ok_codes:
        hint = {
            401: "Token 无效或已过期",
            403: "Token 权限不足(需要勾选 repo 权限)",
            404: "仓库不存在或 Token 无权访问,检查 gh_repo",
        }.get(r.status_code, "")
        die("GitHub 接口 HTTP %s %s %s" % (r.status_code, hint, r.text[:200]))
    return r


def asset_name(path):
    """GitHub 附件名映射:中文会被剥掉,故统一映射成 ASCII 名。
    校园网助手_v1.2_setup.exe -> Windows_v1.2_setup.exe
    校园网助手v1.1.apk        -> Android.v1.1.apk"""
    import re
    if path.name.endswith(".exe"):
        return re.sub(r"^校园网助手", "Windows", path.name)
    if path.name.endswith(".apk"):
        m = re.search(r"v([\d.]+)\.apk$", path.name)
        return "Android.v%s.apk" % m.group(1) if m else path.name
    return path.name


def upload(token, repo, release_id, path):
    name = asset_name(path)
    size = path.stat().st_size
    print("  上传 %s(%.1f MB,视网速可能需要几分钟,请勿关窗)..."
          % (name, size / 1048576))
    url = ("https://uploads.github.com/repos/%s/releases/%s/assets?name=%s"
           % (repo, release_id, urllib.parse.quote(name)))
    # 流式上传：用文件对象代替 read_bytes()，避免 200MB+ 安装包一次性占满内存
    with open(path, "rb") as f:
        r = requests.post(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(size),
                "User-Agent": "campus-helper-deployer",
            },
            data=f,
            timeout=3600,
        )
    if r.status_code not in (201, 202):
        die("上传 %s 失败: HTTP %s %s" % (name, r.status_code, r.text[:300]))
    info = r.json()
    print("  完成: %s" % info["browser_download_url"])
    return info["browser_download_url"]


def main():
    cfg = load_cfg()
    gh_token = (cfg.get("gh_token") or "").strip()
    repo = (cfg.get("gh_repo") or "").strip()
    if not gh_token or "粘贴" in gh_token:
        die("请先在 deploy_config.json 填入 gh_token(GitHub Token,获取步骤见本文件顶部注释)")
    if not repo or "/" not in repo or "用户名" in repo:
        die("请先在 deploy_config.json 填入 gh_repo,格式: 用户名/仓库名")

    # 收集要发布的文件
    uploads = []
    for cfg_key in ("exe_path", "apk_path"):
        p = pathlib.Path(cfg.get(cfg_key) or "")
        if not p.exists():
            die("找不到文件(%s): %s,请检查 deploy_config.json" % (cfg_key, p))
        uploads.append(p)
    print("待发布 %d 个文件: %s" % (len(uploads), ", ".join(f.name for f in uploads)))

    # 1) 检查仓库可达
    gh("GET", "/repos/" + repo, gh_token)
    print("仓库: %s" % repo)

    # 2) 找/建 Release(tag 自动从 exe 文件名提取,如 校园网助手_v1.2_setup.exe -> v1.2)
    import re
    exe_path = pathlib.Path(cfg.get("exe_path") or "")
    m = re.search(r"_v([\d.]+)_setup", exe_path.name)
    if not m:
        die("无法从 exe 文件名识别版本号(应为 校园网助手_vX.Y_setup.exe): %s" % exe_path.name)
    tag = "v" + m.group(1)
    r = gh("GET", "/repos/%s/releases/tags/%s" % (repo, tag), gh_token, ok_codes=(200, 404))
    if r.status_code == 200:
        release = r.json()
        print("Release 已存在: %s" % tag)
    else:
        r = gh("POST", "/repos/%s/releases" % repo, gh_token, json={
            "tag_name": tag,
            "name": tag,
            "body": "校园网助手 %s 安装包(Windows 安装器 + Android 检测版 APK)" % tag,
        }, ok_codes=(201,))
        release = r.json()
        print("已创建 Release: %s" % tag)

    # 3) 同名旧附件先删掉,保证覆盖更新(按 GitHub 上的映射名匹配)
    names = {asset_name(p) for p in uploads}
    for asset in release.get("assets", []):
        if asset["name"] in names:
            gh("DELETE", "/repos/%s/releases/assets/%s"
               % (repo, asset["id"]), gh_token, ok_codes=(204,))
            print("  已删除旧附件: %s" % asset["name"])

    # 4) 上传(376MB 内存直读,现代机器无压力;网速慢请耐心)
    urls = [upload(gh_token, repo, release["id"], p) for p in uploads]

    print("-" * 46)
    print("[成功] 发布完成,下载直链(可填入 data.js 的 downloadUrl):")
    for u in urls:
        print("  %s" % u)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        die("网络请求失败: %s" % e)
