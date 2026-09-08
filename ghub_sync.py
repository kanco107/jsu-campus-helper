# -*- coding: utf-8 -*-
"""
jsu-campus-helper · 全套代码同步到 GitHub(公开仓库)
====================================================
为什么不用 git push:github.com:443 在国内常被墙,但 api.github.com 可通
(即便如此 api 也会偶发断流,本脚本带重试 + blob 缓存断点续传)。
把 e:\\xyw\\jsu-campus-helper 整目录(排除 .gitignore 规则)打成
一个提交推上远端 main。

使用:双击同目录 上传代码到GitHub.cmd
凭据:deploy_config.json(在 校园网助手官网 目录)的 gh_repo / gh_token
"""
import base64
import json
import pathlib
import sys
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG = ROOT.parent / "校园网助手官网" / "deploy_config.json"
CACHE = ROOT / ".ghub_blob_cache.json"
API = "https://api.github.com"
UA = {"User-Agent": "campus-helper-sync"}

# 与 .gitignore 对应的排除规则(纯字符串,posix 前缀匹配)
# 注意:ghub_sync.py 不读取 .gitignore,必须在此同步维护
# 漏排会导致凭据/签名密钥/构建产物被同步到公开 GitHub 仓库
SKIP_DIRS = (".git/", "__pycache__/", "windows/redist/",
             "android/.gradle/", "android/app/build/")
SKIP_FILES = {"deploy_config.json", ".DS_Store", "Thumbs.db",
              ".ghub_blob_cache.json", "android/keystore.properties",
              "android/local.properties"}
SKIP_EXT = {".pyc", ".jks", ".keystore"}

MODE_PLAIN = "100644"
MODE_EXEC = "100755"
EXEC_FILES = {"android/gradlew"}


def die(msg):
    print("[失败] " + msg)
    sys.exit(1)


def make_session():
    s = requests.Session()
    # allowed_methods=None 在新版 urllib3 中语义已变（不再表示"全部方法"），
    # 这里显式列出需要重试的 HTTP 方法（含 POST，因为 GitHub 创建 Release/上传
    # 资源是幂等的，重复请求只会返回已存在的错误，不会产生副作用）。
    retry = Retry(total=4, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE",
                                             "OPTIONS", "TRACE", "POST"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


SESSION = make_session()


def api(method, path, token, ok=(200, 201), **kw):
    last = None
    for attempt in range(4):
        try:
            r = SESSION.request(
                method, API + path,
                headers={"Authorization": "Bearer " + token,
                         "Accept": "application/vnd.github+json", **UA},
                timeout=120, **kw)
            if r.status_code in ok:
                return r.json()
            if r.status_code in (401, 403, 404, 409, 422):
                die("GitHub %s %s -> HTTP %s: %s"
                    % (method, path, r.status_code, r.text[:200]))
            last = "HTTP %s: %s" % (r.status_code, r.text[:150])
        except requests.RequestException as e:
            last = str(e)[:150]
        time.sleep(2 * (attempt + 1))
    die("GitHub %s %s 重试 4 次仍失败: %s" % (method, path, last))


def collect_files():
    files = []
    for p in sorted(ROOT.rglob("*")):
        if p.is_dir():
            continue
        posix = p.relative_to(ROOT).as_posix()
        if any(posix.startswith(d) for d in SKIP_DIRS):
            continue
        # 同时按文件名和相对路径前缀匹配 SKIP_FILES,
        # 让 SKIP_FILES 既可用纯文件名(如 deploy_config.json)也可用路径前缀
        # (如 android/keystore.properties),更直观且不会因 p.name 抹掉目录而漏匹配
        if p.name in SKIP_FILES or posix in SKIP_FILES or \
           any(posix.startswith(s + "/") for s in SKIP_FILES):
            continue
        if p.suffix in SKIP_EXT:
            continue
        files.append(p.relative_to(ROOT))
    return files


def load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c):
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def blob_sha(token, rel, cache):
    """上传 blob;若本地文件未变且缓存有 sha 则直接复用"""
    st = (ROOT / rel).stat()
    key = rel.as_posix()
    hit = cache.get(key)
    if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
        return hit["sha"], False
    data = (ROOT / rel).read_bytes()
    r = api("POST", "/repos/%s/git/blobs" % ROOT_NORM_REPO, token,
            json={"content": base64.b64encode(data).decode(),
                  "encoding": "base64"})
    cache[key] = {"sha": r["sha"], "size": st.st_size, "mtime": st.st_mtime}
    return r["sha"], True


ROOT_NORM_REPO = ""  # 占位,main() 里赋值(保持 blob_sha 签名简单)


def main():
    global ROOT_NORM_REPO
    if not CONFIG.exists():
        die("找不到 " + str(CONFIG))
    cfg = json.loads(CONFIG.read_text("utf-8"))
    token = (cfg.get("gh_token") or "").strip()
    repo = (cfg.get("gh_repo") or "").strip()
    if not token or not token.startswith("ghp_"):
        die("deploy_config.json 的 gh_token 不正确")
    if "/" not in repo:
        die("deploy_config.json 的 gh_repo 应为 用户名/仓库名")
    ROOT_NORM_REPO = repo

    files = collect_files()
    if not files:
        die("没有收集到任何文件")
    total_mb = sum((ROOT / f).stat().st_size for f in files) / 1048576
    print("收集到 %d 个文件(共 %.1f MB)" % (len(files), total_mb))

    # 0) 空仓库先引导出 main(Git Data API 要求仓库非空;空仓库 ref 查询返回 404/409)
    r0 = requests.get(API + "/repos/%s/git/ref/heads/main" % repo,
                      headers={**UA, "Authorization": "Bearer " + token}, timeout=60)
    if r0.status_code in (404, 409):
        gi = ROOT / ".gitignore"
        api("PUT", "/repos/%s/contents/.gitignore" % repo, token, ok=(200, 201), json={
            "message": "初始化仓库",
            "content": base64.b64encode(gi.read_bytes()).decode(),
        })
        print("已引导空仓库(main 分支就绪)")

    # 1) 上传 blobs(带缓存断点续传)
    cache = load_cache()
    entries = []
    fresh = 0
    for f in files:
        sha, uploaded = blob_sha(token, f, cache)
        fresh += uploaded
        mode = MODE_EXEC if f.as_posix() in EXEC_FILES else MODE_PLAIN
        entries.append({"path": f.as_posix(), "mode": mode,
                        "type": "blob", "sha": sha})
        print("  %s %s" % ("上传" if uploaded else "复用", f.as_posix()))
    save_cache(cache)
    print("blob 完成(新上传 %d / 缓存复用 %d)" % (fresh, len(files) - fresh))

    # 2) 建树
    tree = api("POST", "/repos/%s/git/trees" % repo, token, json={"tree": entries})
    print("树已建立: %s" % tree["sha"][:10])

    # 3) 取父提交
    r = requests.get(API + "/repos/%s/git/ref/heads/main" % repo,
                     headers={**UA, "Authorization": "Bearer " + token}, timeout=60)
    if r.status_code != 200:
        die("获取 main 分支失败: HTTP %s" % r.status_code)
    parent = r.json()["object"]["sha"]
    print("父提交: %s" % parent[:10])

    # 4) 建提交
    msg = "备份 " + datetime.now().strftime("%Y-%m-%d %H:%M")
    commit = api("POST", "/repos/%s/git/commits" % repo, token,
                 json={"message": msg, "tree": tree["sha"], "parents": [parent]})
    print("提交: %s %s" % (commit["sha"][:10], msg))

    # 5) 更新分支(父提交即当前头,无需 force)
    api("PATCH", "/repos/%s/git/refs/heads/main" % repo, token,
        json={"sha": commit["sha"], "force": False}, ok=(200,))
    print("[成功] 已同步到 github.com/%s (main)" % repo)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        die("网络请求失败: %s" % e)
