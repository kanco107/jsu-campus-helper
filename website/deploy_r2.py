# -*- coding: utf-8 -*-
"""
校园网助手官网 · 两个安装包(exe + apk)上传到 Cloudflare R2
================================================
一次性前置(在 Cloudflare 控制台手动做,约 5 分钟):
  1. 开通 R2: dash.cloudflare.com 左侧 R2 -> Purchase(选免费额度,
     需绑一张卡或 PayPal 做身份验证,免费额度内不扣费)
  2. 创建存储桶: R2 -> Create bucket,名字与 deploy_config.json 的
     r2_bucket 一致(默认 campus-helper-dl),位置选 APAC
  3. 开启公开访问: 进入桶 -> Settings -> Public Development URL -> Enable
     (得到形如 https://pub-xxxxxx.r2.dev 的公开地址)
  4. 生成上传凭证: R2 -> Manage R2 API Tokens -> Create API Token
     (权限 Object Read & Write,Specify bucket(s) 选刚建的桶)
     把 Access Key ID / Secret Access Key 填进 deploy_config.json

之后每次更新安装包(如出了 v1.2):
  双击 上传安装包.cmd 即可。线上链接固定不变,
  下载对话框里的文件名自动带中文版本号(取自本地文件名)。
"""
import pathlib
import sys
from urllib.parse import quote

from deploy_cf import ApiError, call_api, die, read_config

# 线上对象名固定不变,版本更新直接覆盖同名对象,链接永不失效;
# 用户下载时看到的文件名通过 Content-Disposition 指定为中文版本名。
TARGETS = [
    ("exe_path", "campus-helper-setup.exe"),
    ("apk_path", "campus-helper.apk"),
]


def main():
    cfg, token = read_config()

    # 收集要上传的文件
    uploads = []
    for cfg_key, obj_key in TARGETS:
        p = pathlib.Path(cfg.get(cfg_key) or "")
        if not p.exists():
            die("找不到文件(%s): %s,请检查 deploy_config.json" % (cfg_key, p))
        uploads.append((p, obj_key))

    bucket = (cfg.get("r2_bucket") or "campus-helper-dl").strip()
    ak = (cfg.get("r2_access_key_id") or "").strip()
    sk = (cfg.get("r2_secret_access_key") or "").strip()
    if not ak or not sk:
        die("请先在 deploy_config.json 填入 r2_access_key_id / r2_secret_access_key"
            "(获取步骤见本文件顶部注释)")

    # 1) 确定账号 id:优先用配置里的 account_id,否则用 Token 自动发现
    account_id = (cfg.get("account_id") or "").strip()
    if account_id:
        print("使用配置的账号 id: %s" % account_id)
    else:
        accounts = call_api("GET", "/accounts", token)
        if not accounts:
            die("查不到账号,请在 deploy_config.json 填入 account_id"
                "(控制台任意页面网址 dash.cloudflare.com/ 后面那串 32 位字符)")
        account_id = accounts[0]["id"]
        print("账号: %s" % (accounts[0].get("name") or account_id))

    # 2) S3 兼容客户端(R2 走标准 S3 协议)
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        die("缺少 boto3,请运行: python -m pip install boto3")
    s3 = boto3.client(
        "s3",
        endpoint_url="https://%s.r2.cloudflarestorage.com" % account_id,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        config=Config(signature_version="s3v4"),
    )

    # 3) 桶不存在则自动创建
    try:
        s3.head_bucket(Bucket=bucket)
        print("存储桶已存在: %s" % bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
        print("已自动创建存储桶: %s" % bucket)

    # 4) 逐个上传(大文件自动分片)
    for local, obj_key in uploads:
        total = local.stat().st_size
        done = [0]

        def progress(n, _total=total, _key=obj_key):
            done[0] += n
            print("\r  上传 %s: %d%%" % (_key, done[0] * 100 // max(_total, 1)),
                  end="", flush=True)

        disposition = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
            obj_key, quote(local.name))
        s3.upload_file(
            str(local), bucket, obj_key,
            ExtraArgs={
                "ContentType": "application/octet-stream",
                "ContentDisposition": disposition,
            },
            Callback=progress,
        )
        print()
        print("  完成: %s(%.1f MB,下载时显示为 %s)"
              % (obj_key, total / 1048576, local.name))

    print("-" * 46)
    print("[成功] %d 个安装包已上传到 R2 存储桶 %s" % (len(uploads), bucket))
    print("下载链接 = 公开地址 + 对象名:")
    for _, obj_key in TARGETS:
        print("  https://pub-xxxx.r2.dev/%s" % obj_key)
    print("公开地址(pub-xxxx)在: 控制台 R2 -> %s -> Settings -> Public Development URL"
          % bucket)
    print("拿到后填入 data.js 两个卡片的 downloadUrl,再重新部署网站")


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        die(str(e))
