#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园网助手官网 · 本地开发服务器

用途:
  1. 静态托管整站(GET / 返回 index.html,自动托管 .html/.js/.png/.css)
  2. 提供 POST /save 接口,让 admin.html 编辑后直接写回 data.js

仅监听 127.0.0.1,只对本机开发者开放,不暴露公网。

使用:
  python server.py              # 默认 8000 端口
  python server.py 9000         # 指定端口

启动后访问 http://127.0.0.1:8000/ 看主页,
http://127.0.0.1:8000/admin.html 进管理页。
"""
import sys
import os
import webbrowser
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SITE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SITE_DIR, "data.js")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt":  "text/plain; charset=utf-8",
    ".md":   "text/markdown; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简化日志(显示方法 + 路径 + 状态码)
        # BaseHTTPRequestHandler 默认传 (client_addr, request_line) + 路径特定的 args
        # 标准调用形如 log("code %s, message %s", code, msg),取末位即状态
        status = args[-1] if args else "-"
        sys.stdout.write("[%s] %s -> %s\n" % (self.command, self.path, status))

    def _send_cors(self):
        # 仅本机开发用,允许任意来源(本机浏览器+任意端口)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("", "/"):
            path = "/index.html"
        # 防目录穿越:先规范化再检查是否仍在 SITE_DIR
        norm = os.path.normpath(os.path.join(SITE_DIR, path.lstrip("/")))
        if not norm.startswith(SITE_DIR + os.sep) and norm != SITE_DIR:
            self.send_error(400, "Bad Request")
            return
        file_path = norm
        if not os.path.isfile(file_path):
            self.send_error(404, "Not Found: " + path)
            return
        ext = os.path.splitext(file_path)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(file_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._send_cors()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(500, "Internal Server Error: " + str(e))

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/save":
            self.send_error(404, "Not Found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            # 限制请求体大小，防止误传巨量内容撑爆 data.js（data.js 正常只有几十 KB）
            if length > 1024 * 1024:
                self._send_json(413, {"ok": False, "error": "content too large (>1MB)"})
                return
            raw = self.rfile.read(length) if length else b""
            data = json.loads(raw.decode("utf-8") or "{}")
            content = data.get("content")
            if not isinstance(content, str) or not content.strip():
                self._send_json(400, {"ok": False, "error": "missing content"})
                return
            # 严格校验：必须以 window.SITE_DATA 开头，且包含完整的对象结构
            stripped = content.lstrip()
            if not stripped.startswith("window.SITE_DATA"):
                self._send_json(400, {"ok": False, "error": "content must start with 'window.SITE_DATA'"})
                return
            # 必须是合法 JS 对象字面量（粗略检查花括号配对，避免写坏整站）
            if content.count("{") != content.count("}") or content.count("{") == 0:
                self._send_json(400, {"ok": False, "error": "unbalanced braces in content"})
                return
            # 二进制写入 + 原子替换，防止写入中途崩溃导致 data.js 损坏
            raw_content = content.encode("utf-8")
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "wb") as f:
                f.write(raw_content)
            os.replace(tmp, DATA_FILE)
            self._send_json(200, {"ok": True, "message": "saved", "bytes": len(raw_content)})
        except json.JSONDecodeError as e:
            self._send_json(400, {"ok": False, "error": "invalid JSON: " + str(e)})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)


def find_port(preferred):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            pass
    # 找一个可用端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("端口参数无效,使用默认 %d" % DEFAULT_PORT)
    port = find_port(port)
    server = ThreadingHTTPServer((HOST, port), Handler)
    url_home = "http://%s:%d/" % (HOST, port)
    url_admin = "http://%s:%d/admin.html" % (HOST, port)
    print("=" * 60)
    print("校园网助手官网 · 本地开发服务器")
    print("=" * 60)
    print("主 页: %s" % url_home)
    print("管理页: %s" % url_admin)
    print("静默保存目标: %s" % DATA_FILE)
    print("按 Ctrl+C 退出")
    print("-" * 60)
    # 自动开浏览器进管理页(方便)
    try:
        webbrowser.open(url_admin)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
        server.shutdown()


if __name__ == "__main__":
    main()
