# -*- coding: utf-8 -*-
"""
校园网助手 · 全套代码备份到 Gitee(私有仓库)
================================================
首次配置(一次性):
  1. deploy_config.json(在 校园网助手官网 目录)里填:
     gitee_repo  = 你的Gitee用户名/jsu-campus-helper
     gitee_token = Gitee 私人令牌(生成:Gitee 头像 -> 设置 ->
                   安全设置 -> 私人令牌 -> 生成新令牌,勾选 projects)
  2. Gitee 上先建好同名【私有】【空】仓库(不要勾选任何初始化文件)

之后每次备份:双击本目录的 上传代码到Gitee.cmd
  自动 add + commit + push,改名"备份 <日期>"。
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
GIT = ROOT.parent / "PortableGit" / "cmd" / "git.exe"
CONFIG = ROOT.parent / "校园网助手官网" / "deploy_config.json"


def die(msg):
    print("[失败] " + msg)
    sys.exit(1)


def run(args, **kw):
    kw.setdefault("cwd", str(ROOT))
    # 禁止 git 在认证失败时弹出交互式凭据提示（会导致脚本挂起等待输入）；
    # 认证失败直接返回错误码，由调用方处理。
    env = dict(kw.pop("env", None) or __import__("os").environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    if not GIT.exists():
        die("找不到 PortableGit: %s" % GIT)
    if not CONFIG.exists():
        die("找不到配置: %s" % CONFIG)
    cfg = json.loads(CONFIG.read_text("utf-8"))
    repo = (cfg.get("gitee_repo") or "").strip()
    token = (cfg.get("gitee_token") or "").strip()
    if not repo or "用户名" in repo or "/" not in repo:
        die("请先在 deploy_config.json 填 gitee_repo(格式: 用户名/jsu-campus-helper)")
    if not token:
        die("请先在 deploy_config.json 填 gitee_token(Gitee 私人令牌,勾选 projects 权限)")

    # 1) 暂存全部变更
    code, out = run([str(GIT), "add", "-A"])
    if code:
        die("git add 失败: %s" % out)

    # 2) 有变更才提交(首次必提交)
    code, head = run([str(GIT), "rev-parse", "--verify", "HEAD"])
    code2, dirty = run([str(GIT), "status", "--porcelain"])
    if code2:
        die("git status 失败: %s" % dirty)
    if code != 0 or dirty.strip():
        msg = "备份 " + datetime.now().strftime("%Y-%m-%d %H:%M")
        code, out = run([str(GIT), "-c", "user.name=campus-helper",
                         "-c", "user.email=campus-helper@jsu.local",
                         "commit", "-m", msg])
        if code:
            die("git commit 失败: %s" % out)
        print("已提交: %s" % msg)
    else:
        print("没有新变更,跳过提交")

    # 3) 推送(Gitee 标准令牌认证:oauth2 用户名 + 令牌,不回显)
    url = "https://oauth2:%s@gitee.com/%s.git" % (token, repo)
    code, out = run([str(GIT), "push", "-u", url, "main"], cwd=str(ROOT))
    if code:
        # 兼容首推时远端分支名
        code2, out2 = run([str(GIT), "push", "-u", url, "master"], cwd=str(ROOT))
        if code2:
            die("git push 失败(检查仓库名/令牌是否正确、仓库是否已建好):\n%s" % (out + out2)[-600:])
    print("[成功] 代码已备份到 Gitee: %s" % repo)


if __name__ == "__main__":
    main()
