# -*- coding: utf-8 -*-
"""校园网自动连接与修复工具（核心逻辑模块，仅支持 Windows 10 及以上系统）。

设计说明（CLI 与图形界面共用同一套核心）：
- 所有用户可见的输出均通过 log 回调发出，UI 可用自己的日志控件接收；
- 所有需要用户决策的环节（选择 WiFi、输入学号密码/运营商）均通过 Interaction
  交互对象完成，核心逻辑不使用 input()；CLI 与 UI 各自实现子类即可接管交互；
- 所有可变参数集中在 config.json 中，首次运行自动生成默认配置，UI 可直接读写该文件；
- 用户在交互中做出的选择（WiFi 名称、运营商、账号）会被记住并写回配置，下次免问；
- CLI 入口见本文件 main()；图形界面入口见 app.py。
"""

import ctypes
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import psutil
import requests
from requests.exceptions import RequestException, Timeout

if os.name == "nt":
    import winreg
else:  # 非 Windows 环境下保证模块可加载，实际功能在入口处拦截
    winreg = None

# 打包为无控制台 GUI 程序（console=False）后，GUI 进程本身没有控制台；此时若派生
# ping/netsh/ipconfig 等控制台程序，Windows 会为其新建一个控制台窗口（标题类似
# C:\Windows\SYSTEM32\ping.exe）。这里在“进程级别”统一给所有 subprocess 调用注入
# CREATE_NO_WINDOW + SW_HIDE：无论代码里哪条命令、哪个第三方库发起，都不会再弹黑窗。
# 注意：下面通过 monkey-patch subprocess.Popen.__init__ 全局注入，无需在每次调用时再传参。


def _log_to_file(msg):
    """调试日志：写入用户数据目录的 wlan_debug.log（仅用于排查 WiFi 信号读取问题）。
    超过 512KB 时清空重写，避免长期运行无限增长（与 app.py 的 debug.log 轮转策略一致）。"""
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "校园网助手", "wlan_debug.log")
        if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
if os.name == "nt":
    _CREATE_NO_WINDOW = 0x08000000
    _orig_popen_init = subprocess.Popen.__init__

    def _popen_init_no_window(self, *args, **kwargs):
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | _CREATE_NO_WINDOW
        si = kwargs.get("startupinfo")
        if si is None:
            si = subprocess.STARTUPINFO()
            kwargs["startupinfo"] = si
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _popen_init_no_window

# ============================ 配置 ============================

# 默认配置（config.json 不存在时自动按此生成，防止用户改坏后可随时删除还原）
DEFAULT_CONFIG = {
    "gateway": "192.168.254.17",                        # 校园网网关（内网检测地址）
    "auth_url": "http://192.168.254.17/drcom/login",    # 认证服务器登录地址
    "carrier": "cmcc",                                  # 运营商线路: cmcc移动 / ctcc电信 / cucc联通
    "wifi_ssid": "JSU-WLAN-DORM",                       # 首选 WiFi 名称（用户选择后自动记住，优先直连）
    "wifi_keyword": "DORM",                             # WiFi 名称筛选关键字（大小写不敏感，留空则列出全部）
    "public_test_host": "223.5.5.5",                    # 外网连通性测试地址
    "test_domain": "www.baidu.com",                     # 域名解析测试域名
    "dns_primary": "223.5.5.5",                         # 首选备用 DNS（公共）
    "dns_secondary": "223.6.6.6",                       # 次选备用 DNS（公共）
    "campus_dns_primary": "210.43.64.10",               # 校内首选 DNS
    "campus_dns_secondary": "210.43.64.11",             # 校内次选 DNS
    "ping_timeout": 10,                                 # 单次 ping 超时（秒）
    "login_timeout": 5,                                 # 登录请求超时（秒）
    "portal_url": "http://192.168.254.17/",             # 认证页面地址（弹窗页面登录用）
    "status_url": "http://192.168.254.17/drcom/chkstatus",  # 在线状态查询接口（drcom 固件）
    "last_account": "",                                 # 最近一次成功认证的账号（自动学习，用于预填）
    # drcom 协议参数（固件升级可能变化，需调整时直接改 config.json，不在 UI 中暴露）
    "drcom_params": {
        "callback": "dr1003",
        "0MKKey": "123456",
        "R1": "0",
        "R2": "",
        "R3": "0",
        "R6": "0",
        "para": "00",
        "v6ip": "",
        "terminal_type": "1",
        "lang": "zh-cn",
        "jsVersion": "4.2",
        "v": "7081",
    },
}

CONFIG_FILENAME = "config.json"

# Windows 用户级代理设置所在注册表位置
INTERNET_SETTINGS_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# 运营商代码 -> 显示名称（UI 下拉框可直接使用）
CARRIER_NAMES = {
    "cmcc": "中国移动",
    "ctcc": "中国电信",
    "cucc": "中国联通",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36",
]

VIRTUAL_ADAPTER_KEYWORDS = ["vEthernet", "Virtual", "Loopback", "Tunnel", "Software", "ISATAP"]


def get_data_dir():
    """用户数据目录（可写）：存放 config.json、WebView2 缓存等运行期数据。

    安装到 C:\\Program Files 后 exe 同目录对普通用户只读，因此打包版统一
    使用 %LOCALAPPDATA%\\校园网助手；开发（非打包）时用脚本目录，方便调试。
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        data_dir = os.path.join(base, "校园网助手")
    else:
        data_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass
    return data_dir


def get_config_path():
    """config.json 存放于用户数据目录（可写）。
    PyInstaller 打包后使用 %LOCALAPPDATA%\\校园网助手（Program Files 不可写）；
    若 exe 同目录存在旧版 config.json（免安装版习惯），首次自动迁移。"""
    if getattr(sys, "frozen", False):
        new_path = os.path.join(get_data_dir(), CONFIG_FILENAME)
        try:
            old_path = os.path.join(os.path.dirname(sys.executable), CONFIG_FILENAME)
            if os.path.exists(old_path) and not os.path.exists(new_path):
                import shutil
                shutil.copy2(old_path, new_path)
        except Exception:
            pass
        return new_path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)


def get_resource_dir():
    """只读资源（如 ui 模板）所在目录。打包后从 _MEIPASS 读取。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def load_config(path=None, create_if_missing=True):
    """加载配置；缺失的键自动用默认值补齐，文件不存在时可自动生成。"""
    path = path or get_config_path()
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                # drcom_params 做深合并：用户只改个别键时不丢失其余默认参数
                # （浅合并会整个覆盖，导致 callback/0MKKey 等丢失、登录失败）
                if isinstance(user_cfg.get("drcom_params"), dict):
                    merged_params = dict(DEFAULT_CONFIG["drcom_params"])
                    merged_params.update(user_cfg["drcom_params"])
                    user_cfg["drcom_params"] = merged_params
                config.update(user_cfg)
        except (OSError, json.JSONDecodeError) as e:
            print(f"读取配置文件失败（将使用默认配置）: {e}")
    elif create_if_missing:
        save_config(config, path)
    return config


def save_config(config, path=None):
    """保存配置（UI 修改配置后调用）。先写临时文件再原子替换，防止写入中途崩溃导致文件损坏。"""
    path = path or get_config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)
    return path


# ============================ 更改还原日志（撤销所有更改） ============================
# 工具每次修改系统（IP/DNS/代理/网卡/随机 MAC/WiFi 配置）前，都会把原始状态记录到
# revert_state.json；“撤销所有更改”按记录逆向恢复，避免工具本身让用户彻底断网。

REVERT_FILENAME = "revert_state.json"


def get_revert_state_path():
    """revert_state.json 存放于用户数据目录（打包后 _MEIPASS 只读，
    必须放到 %LOCALAPPDATA%；开发时用脚本目录）。"""
    return os.path.join(get_data_dir(), REVERT_FILENAME)


def load_revert_entries():
    path = get_revert_state_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_revert_entries(entries):
    try:
        path = get_revert_state_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def record_revert_entry(entry):
    """记录一项更改的还原信息。

    同一网卡的 IP / DNS 原始配置只保留第一次记录（防止后续运行把
    工具自己改过的状态当成“原始状态”）；其余类型跳过完全相同的重复项。
    """
    entries = load_revert_entries()
    etype = entry.get("type")
    if etype in ("address", "dns"):
        card = entry.get("card", "")
        if any(e.get("type") == etype and e.get("card") == card for e in entries):
            return
    elif any(e == entry for e in entries):
        return
    entries.append(entry)
    save_revert_entries(entries)


def prefix_to_mask(prefix):
    """把子网前缀长度（如 24）转换为子网掩码（如 255.255.255.0）。"""
    prefix = max(0, min(32, int(prefix)))
    bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return "{}.{}.{}.{}".format((bits >> 24) & 255, (bits >> 16) & 255, (bits >> 8) & 255, bits & 255)


def _console_encoding():
    """Windows 控制台命令（ping/netsh/ipconfig）输出使用的代码页。

    优先用 GetConsoleOutputCP()：它反映实际控制台输出编码。
    当用户开了"Beta: 使用 UTF-8 提供全球语言支持"时，控制台输出 CP 为 65001
    (UTF-8)，netsh/ping 的输出也是 UTF-8；此时若用 GetOEMCP() 返回的 936
    (GBK) 去解码，中文标签会全乱码。

    未开 UTF-8 Beta 的中文系统：GetConsoleOutputCP 返回 936，用 gb18030 解码。
    """
    if os.name == "nt":
        try:
            # GetConsoleOutputCP 是实际控制台输出编码，netsh/ping 输出跟随这个值
            cocp = ctypes.windll.kernel32.GetConsoleOutputCP()
            if cocp == 65001:
                return "utf-8"
            if cocp:
                if cocp == 936:
                    return "gb18030"  # GBK 超集，对中文兼容性最好
                import codecs
                return codecs.lookup("cp%d" % cocp).name
            # 回退到 OEM 代码页
            oem = ctypes.windll.kernel32.GetOEMCP()
            if oem:
                if oem == 936:
                    return "gb18030"
                import codecs
                return codecs.lookup("cp%d" % oem).name
        except Exception:
            pass
    import locale
    return locale.getpreferredencoding(False) or "utf-8"


def _decode_bytes(data):
    """解码命令行输出（ping/netsh 等返回 bytes）。

    顺序：先按 UTF-8 严格解码（纯 ASCII / UTF-8 环境直接成功）；
    失败再按 Windows 控制台代码页（中文系统 GBK）解码；都失败再 UTF-8 兜底。
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")  # 纯 ASCII 与 UTF-8 环境在此成功
    except (UnicodeDecodeError, LookupError):
        pass
    try:
        return data.decode(_console_encoding(), errors="replace")
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def is_supported_windows():
    """本程序仅支持 Windows 10 及以上版本（build >= 10240）。"""
    if os.name != "nt":
        return False
    try:
        return sys.getwindowsversion().build >= 10240
    except AttributeError:  # 极老的 Python 不提供该接口
        return False


# ============================ 用户交互抽象 ============================

class Interaction:
    """用户交互抽象：核心逻辑通过它向用户提问，CLI / GUI 各自实现子类。

    interaction 为 None 时表示“全自动模式”，核心逻辑遇到需要用户决策的环节
    一律跳过，绝不阻塞（适合无人值守场景）。
    """

    def pick_wifi(self, candidates, current_ssid=""):
        """让用户选择要连接的 WiFi。

        :param candidates: [{"ssid": str, "signal": int, "auth": str}]，已按相关性排序
        :param current_ssid: 当前已连接的 SSID（用于标记）
        :return: 选中的 SSID；空串 / None 表示用户跳过
        """
        raise NotImplementedError

    def get_credentials(self, last_account="", prefill_carrier="cmcc"):
        """获取校园网认证所需的学号 / 密码 / 运营商。

        :param last_account: 上次成功认证的账号（用于预填）
        :param prefill_carrier: 默认运营商代码
        :return: (student_id, password, carrier) 三元组；
                 None 表示用户取消；
                 也可返回 {"portal_login": True, "account": ..., "carrier": ...}
                 表示用户已通过弹出的认证页面完成登录。
        """
        raise NotImplementedError

    def pick_adapter(self, candidates):
        """多网卡同时连接校园网时，让用户选择保留哪一张。

        :param candidates: 校园网可达的网卡名列表，如 ["以太网", "WLAN"]
        :return: 保留的网卡名；None/空 表示跳过（不改动任何网卡）
        """
        raise NotImplementedError


class CliInteraction(Interaction):
    """命令行交互：终端问答实现。"""

    def pick_wifi(self, candidates, current_ssid=""):
        if not candidates:
            return ""
        print("检测到多个候选无线网络：")
        for i, n in enumerate(candidates, 1):
            sec = "开放" if is_open_network(n) else "加密"
            mark = "  [当前已连接]" if n["ssid"] == current_ssid else ""
            print(f"  {i}. {n['ssid']}（{sec}，信号 {n.get('signal', '?')}%）{mark}")
        print("  0. 手动输入 WiFi 名称")
        print("  直接回车 = 跳过")
        while True:
            choice = input("请选择要连接的 WiFi: ").strip()
            if choice == "":
                return ""
            if choice == "0":
                return input("请输入 WiFi 名称: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1]["ssid"]
            print("输入无效，请重新选择。")

    def get_credentials(self, last_account="", prefill_carrier="cmcc"):
        if prefill_carrier not in CARRIER_NAMES:
            prefill_carrier = "cmcc"
        tip = f"（直接回车使用上次账号 {last_account}）" if last_account else ""
        sid = input(f"请输入学号{tip}: ").strip() or last_account
        if not sid:
            return None
        pwd = input("请输入密码: ").strip()
        if not pwd:
            return None
        print("运营商线路：1.中国移动(cmcc)  2.中国电信(ctcc)  3.中国联通(cucc)")
        raw = input(f"请选择（直接回车默认 {CARRIER_NAMES[prefill_carrier]}）: ").strip().lower()
        carrier = {"1": "cmcc", "2": "ctcc", "3": "cucc"}.get(raw, raw)
        if carrier not in CARRIER_NAMES:
            carrier = prefill_carrier
        return sid, pwd, carrier

    def pick_adapter(self, candidates):
        if not candidates:
            return ""
        print("检测到多张网卡同时连接校园网（认证系统限制终端数量时会互相挤掉线）：")
        for i, name in enumerate(candidates, 1):
            print(f"  {i}. {name}")
        print("  直接回车 = 跳过（不改动任何网卡）")
        while True:
            choice = input("请选择要保留的网卡: ").strip()
            if choice == "":
                return ""
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1]
            print("输入无效，请重新选择。")


# ============================ WiFi 扫描与选择 ============================

def scan_wifi_networks():
    """扫描周围可见的 WiFi 网络。

    :return: [{"ssid": str, "signal": int(0-100), "auth": str}]，按信号强度降序；
             同名网络自动合并（多 BSSID 取最强信号）。失败返回空列表。
    """
    try:
        output = subprocess.check_output(
            ["netsh", "wlan", "show", "networks", "mode=Bssid"],
            stderr=subprocess.STDOUT, timeout=15,
        )
    except Exception:
        return []
    return _parse_wifi_output(_decode_bytes(output))


def _parse_wifi_output(text):
    """解析 netsh wlan show networks mode=Bssid 的输出（兼容中英文系统）。"""
    networks = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"\s*SSID\s+\d+\s*:\s?(.*)$", line)
        if m:  # "SSID 1 : XXX" 行（隐藏网络的 SSID 为空，跳过）
            current = m.group(1).strip() or None
            if current and current not in networks:
                networks[current] = {"ssid": current, "signal": 0, "auth": ""}
            continue
        if current is None:
            continue
        m = re.search(r"(\d+)\s*%", line)  # 信号行（"信号 : 82%" / "Signal : 82%"）
        if m:
            networks[current]["signal"] = max(networks[current]["signal"], int(m.group(1)))
            continue
        if ("身份验证" in line or "认证" in line
                or "authentication" in line.lower()):
            _, _, val = line.partition(":")
            networks[current]["auth"] = val.strip()
    result = list(networks.values())
    result.sort(key=lambda n: n["signal"], reverse=True)
    return result


def is_open_network(net):
    """判断 WiFi 是否为开放（无密码）网络：开放式 / Open / 加密为无。"""
    auth = (net.get("auth") or "").strip()
    if not auth or "无" == auth:
        return True
    return ("开放" in auth) or auth.upper().startswith("OPEN")


def format_mac(mac):
    """把 12 位 MAC 字符串格式化为 AA:BB:CC:DD:EE:FF 便于阅读。"""
    mac = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    if len(mac) < 12:
        return mac or ""
    return ":".join(mac[i:i + 2] for i in range(0, 12, 2)).upper()


def is_random_mac(mac):
    """判断 MAC 是否为“本地管理地址”（Windows 随机硬件地址的特征）。

    真实网卡出厂 MAC 为“普遍管理地址”（首字节第 2 位为 0）；
    Windows 随机硬件地址生成的 MAC 首字节第 2 位为 1。
    """
    mac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(mac) < 2:
        return False
    try:
        first = int(mac[:2], 16)
    except ValueError:
        return False
    return bool(first & 0x02)


def filter_wifi_candidates(networks, keyword):
    """按关键字筛选候选 WiFi（大小写不敏感），按信号强度排序。

    关键字无命中时，回退为全部开放网络（无需密码可直接连接），
    避免关键字配置错误导致列表为空。
    """
    keyword = (keyword or "").strip().upper()
    if keyword:
        matched = [n for n in networks if keyword in (n.get("ssid") or "").upper()]
        if matched:
            return matched
    fallback = [n for n in networks if is_open_network(n)]
    fallback.sort(key=lambda n: n["signal"], reverse=True)
    return fallback


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def create_open_wifi_profile(ssid):
    """为开放（无密码）WiFi 创建 WLAN 配置文件。

    未保存过配置的网络 netsh wlan connect 无法直连，需先写入配置文件（幂等，
    重复创建只是覆盖）。返回是否成功。
    """
    profile = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{_xml_escape(ssid)}</name>
  <SSIDConfig><SSID><name>{_xml_escape(ssid)}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>auto</connectionMode>
  <MSM><security><authEncryption>
    <authentication>open</authentication>
    <encryption>none</encryption>
    <useOneX>false</useOneX>
  </authEncryption></security></MSM>
</WLANProfile>"""
    tmp = os.path.join(os.environ.get("TEMP", "."), "campus_wifi_profile.xml")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(profile)
        result = subprocess.run(
            ["netsh", "wlan", "add", "profile", f"filename={tmp}"],
            capture_output=True, timeout=20,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ============================ 核心逻辑 ============================

class CampusNetworkFixer:
    """封装全部网络检测 / 修复能力，供 CLI 与 UI 共同调用。"""

    def __init__(self, config=None, log=None, interaction=None):
        """
        :param config: 配置字典（一般传入 load_config() 的结果）
        :param log: 消息输出回调，签名 log(str)。UI 传入自己的日志函数即可接管全部输出。
        :param interaction: Interaction 实例（选 WiFi / 要账号密码时回调）；
                            None 表示全自动模式，需要用户决策的环节一律跳过。
        """
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.log = log or print
        self.interaction = interaction
        self.carrier_override = None      # 交互中选择的运营商线路（优先于配置）
        self._credentials_declined = False  # 用户取消输入后，本次流程不再重复询问

    # ---------- 环境检测 ----------

    @staticmethod
    def is_admin():
        """是否以管理员身份运行（netsh 需要管理员权限）。"""
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return True  # 非 Windows 或检测失败时不阻塞流程

    def get_enabled_physical_netcards_with_ipv4(self):
        stats_info = psutil.net_if_stats()
        addresses_info = psutil.net_if_addrs()

        physical = [c for c in stats_info
                    if not any(k in c for k in VIRTUAL_ADAPTER_KEYWORDS)]
        enabled = [c for c in physical if stats_info[c].isup]

        with_ipv4 = []
        for card in enabled:
            for addr in addresses_info.get(card, []):
                if addr.family == socket.AF_INET:
                    with_ipv4.append(card)
                    break
        return with_ipv4

    def get_physical_adapter_ip_states(self):
        """获取所有已连接（链路启用）物理网卡的 IPv4 状态，用于硬件故障判定。

        :return: [{"name": 网卡名, "connected": True,
                   "ipv4": 首个正常 IPv4 地址（无则空串）,
                   "link_local": 是否只拿到 169.254.x.x 链路本地地址}]
        """
        stats_info = psutil.net_if_stats()
        addresses_info = psutil.net_if_addrs()
        states = []
        for card, st in stats_info.items():
            if any(k in card for k in VIRTUAL_ADAPTER_KEYWORDS) or not st.isup:
                continue
            ipv4, link_local = "", False
            for addr in addresses_info.get(card, []):
                if addr.family != socket.AF_INET or not addr.address:
                    continue
                if addr.address.startswith("169.254."):
                    link_local = True
                elif not ipv4:
                    ipv4 = addr.address
            states.append({"name": card, "connected": True,
                           "ipv4": ipv4, "link_local": link_local and not ipv4})
        return states

    # ---------- 基础网络操作 ----------

    def ping_host(self, host, timeout=None, quiet=False, source_ip=None):
        timeout = timeout or self.config["ping_timeout"]
        command = ["ping", "-n", "1", "-w", str(int(timeout * 1000))]
        if source_ip:
            command += ["-S", source_ip]  # 绑定源地址：只测指定网卡的连通性
        command.append(host)
        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.STDOUT,
                timeout=timeout + 5,
            )
        except subprocess.TimeoutExpired:
            if not quiet:
                self.log(f"Ping {host} 超时。")
            return False
        except subprocess.CalledProcessError as e:
            if not quiet:
                self.log(f"Ping {host} 失败: {_decode_bytes(e.output).strip()}")
            return False
        except OSError as e:
            if not quiet:
                self.log(f"Ping {host} 时发生错误: {e}")
            return False

        decoded = _decode_bytes(output)
        if "TTL" in decoded:
            return True
        if not quiet:
            self.log(f"Ping 输出（调试用）: {decoded.strip()}")
        return False

    def _run(self, command, timeout=60):
        """执行系统命令。

        传入 list 时使用 shell=False（参数不经 shell 解析，杜绝 SSID/网卡名
        中的特殊字符被 cmd.exe 当作命令分隔符执行的注入风险）；
        传入 str 时保留 shell=True（仅用于无用户输入的静态命令）。

        编码：必须用 OEM 代码页（GetOEMCP）而非系统默认。若用户开了
        "Beta: 使用 UTF-8 提供全球语言支持"，locale.getpreferredencoding()
        会返回 utf-8，但 netsh/ping 仍按 GBK 输出 → 中文标签全乱码。
        """
        enc = _console_encoding()
        try:
            if isinstance(command, list):
                return subprocess.run(
                    command, shell=False, capture_output=True,
                    encoding=enc, errors="replace", timeout=timeout,
                )
            return subprocess.run(
                command, shell=True, capture_output=True,
                encoding=enc, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            self.log(f"命令执行超时: {command}")
            return subprocess.CompletedProcess(command, -1, "", str(e))

    def get_wifi_state(self):
        """查询无线网卡状态。返回 (wlan 可用, 当前已连接的 SSID)。"""
        info = self.get_wlan_info()
        return info["ok"], info["ssid"]

    def get_wlan_info(self):
        """查询无线网卡详细信息。

        :return: {"ok": 是否有可用无线网卡, "ssid": 当前连接的 SSID,
                  "name": 接口名称, "mac": 当前 MAC（无分隔符小写）, "signal": RSSI dBm}
        """
        result = self._run("netsh wlan show interfaces", timeout=15)
        if result.returncode != 0:
            return {"ok": False, "ssid": "", "name": "", "mac": "", "signal": -100}
        raw = result.stdout or ""
        # 调试：记录原始输出前 500 字符，排查编码/格式问题
        try:
            _log_to_file(f"get_wlan_info raw (len={len(raw)}): {raw[:500]}")
        except Exception:
            pass
        out = {"ok": True, "ssid": "", "name": "", "mac": "", "signal": -100}
        for line in raw.splitlines():
            if not out["ssid"]:
                m = re.match(r"\s*SSID\s*:\s*(.*?)\s*$", line)  # 不会误匹配 BSSID 行
                if m and m.group(1):
                    out["ssid"] = m.group(1)
            if not out["name"]:
                m = re.match(r"\s*(?:名称|Name)\s*:\s*(.+?)\s*$", line)
                if m:
                    out["name"] = m.group(1)
            if not out["mac"]:
                m = re.match(r"\s*(?:物理地址|MAC\s*地址|MAC\s*Address|Physical Address)\s*:\s*([0-9A-Fa-f:-]{12,17})\s*$", line)
                if m:
                    out["mac"] = re.sub(r"[^0-9a-fA-F]", "", m.group(1)).lower()
            # 信号强度：netsh 输出 "信号 : 82%" 或 "Signal : 82%"
            # 兼容中文系统可能的全角冒号"："，以及"信号强度"等变体
            m = re.match(r"\s*(?:信号(?:强度)?|Signal)\s*[:：]\s*(\d+)\s*%", line)
            if m:
                pct = int(m.group(1))
                # netsh 的信号百分比映射到 RSSI 近似值：
                # 100%≈-50dBm（极好），0%≈-100dBm（极差），线性插值
                out["signal"] = round(-50 - (100 - pct) * 0.5)
            # 备用：直接读 RSSI 行（"Rssi : -28"），比百分比转换更准确
            m = re.match(r"\s*(?:Rssi|RSSI)\s*[:：]\s*(-?\d+)", line)
            if m:
                out["signal"] = int(m.group(1))
            if out["ssid"] and out["name"] and out["mac"] and out["signal"] != -100:
                break
        try:
            _log_to_file(f"get_wlan_info result: ssid={out['ssid']}, signal={out['signal']}")
        except Exception:
            pass
        return out

    def set_dhcp_and_renew(self, netcard):
        """将指定网卡恢复为 DHCP 并释放 / 更新 IP 和 DNS。"""
        # 每个元素: (命令, 成功日志, 失败日志, 是否关键步骤)
        # 关键步骤失败时提前返回，避免后续步骤产生无意义错误。
        steps = [
            (["netsh", "interface", "ip", "set", "address", f"name={netcard}", "source=dhcp"],
             f"{netcard} 的 IP 地址已设置为 DHCP", f"设置 {netcard} 的 IP 地址为 DHCP 失败", True),
            (["netsh", "interface", "ip", "set", "dns", f"name={netcard}", "source=dhcp"],
             f"{netcard} 的 DNS 已设置为 DHCP", f"设置 {netcard} 的 DNS 为 DHCP 失败", False),
            (["ipconfig", "/release", netcard],
             f"{netcard} 的 IP 地址已释放", f"释放 {netcard} 的 IP 地址失败", False),
            (["ipconfig", "/renew", netcard],
             f"{netcard} 的 IP 地址已更新", f"更新 {netcard} 的 IP 地址失败", True),
        ]
        for command, ok_msg, fail_msg, critical in steps:
            result = self._run(command)
            if result.returncode == 0:
                self.log(f"{ok_msg}。")
                time.sleep(2)
            else:
                self.log(f"{fail_msg}。错误: {result.stdout}\n{result.stderr}")
                if critical:
                    self.log("关键步骤失败，终止 DHCP 配置流程。")
                    return
                time.sleep(5)

    def set_custom_dns(self, netcard, primary_dns, secondary_dns):
        result = self._run(
            ["netsh", "interface", "ip", "set", "dns", f"name={netcard}",
             "source=static", f"addr={primary_dns}", "register=PRIMARY"])
        if result.returncode == 0:
            self.log(f"{netcard} 的主 DNS 已设置为 {primary_dns}。")
        else:
            self.log(f"设置 {netcard} 的主 DNS 失败。错误: {result.stdout}\n{result.stderr}")

        result = self._run(
            ["netsh", "interface", "ip", "add", "dns", f"name={netcard}",
             f"addr={secondary_dns}", "index=2"])
        if result.returncode == 0:
            self.log(f"{netcard} 的备用 DNS 已设置为 {secondary_dns}。")
        else:
            self.log(f"设置 {netcard} 的备用 DNS 失败。错误: {result.stdout}\n{result.stderr}")

    def flush_dns_cache(self):
        result = self._run("ipconfig /flushdns")
        if result.returncode == 0:
            self.log("DNS 缓存已清除。")
        else:
            self.log(f"清除 DNS 缓存失败。错误: {result.stdout}\n{result.stderr}")
        time.sleep(2)

    def connect_wifi(self, ssid, wait=15):
        """发送 WiFi 连接请求并轮询确认是否连上（netsh 连接是异步的）。"""
        result = self._run(["netsh", "wlan", "connect", f"name={ssid}"], timeout=20)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode != 0:
            reason = output.splitlines()[0].strip() if output else "未知原因"
            self.log(f"发送连接 {ssid} 的请求失败：{reason}")
            return False
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(2)
            _, current = self.get_wifi_state()
            if current == ssid:
                self.log(f"已成功连接无线网络 {ssid}。")
                return True
        self.log(f"等待连接 {ssid} 超时（可能信号弱、网络需要密码或已断开）。")
        return False

    def find_campus_connected_adapters(self):
        """找出同时连接到校园网（能以自身 IP 为源 ping 通网关）的物理网卡。

        认证系统按终端数量限制时，多张网卡（不同 MAC）会被判定为多台终端，
        互相挤下线导致反复掉线，因此需要识别并让用户选择只保留一张。
        """
        result = []
        addrs = psutil.net_if_addrs()
        for card in self.get_enabled_physical_netcards_with_ipv4():
            ip = next((a.address for a in addrs.get(card, []) if a.family == socket.AF_INET), None)
            if not ip:
                continue
            # 以该网卡的 IP 为源地址 ping 网关：只有真正连着校园网的网卡才通
            if self.ping_host(self.config["gateway"], timeout=3, quiet=True, source_ip=ip):
                result.append(card)
        return result

    def _set_wlan_randomization(self, ssid, enable):
        """把指定 WLAN 配置文件的“随机硬件地址”设为开启/关闭。

        做法：导出配置文件 XML -> 改写 <MacRandomization><enableRandomization>
        -> 重新导入。重新连接 WiFi 后生效。
        """
        target = "true" if enable else "false"
        state = "开启" if enable else "关闭"
        tmpdir = tempfile.mkdtemp(prefix="campus_wlan_")
        try:
            result = self._run(["netsh", "wlan", "export", "profile",
                                f"name={ssid}", f"folder={tmpdir}"], timeout=20)
            files = [f for f in os.listdir(tmpdir) if f.lower().endswith(".xml")]
            if result.returncode != 0 or not files:
                detail = ((result.stdout or "") + (result.stderr or "")).strip()
                self.log(f"导出 WLAN 配置文件失败：{detail}")
                return False
            path = os.path.join(tmpdir, files[0])
            with open(path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            if "<MacRandomization>" in content:
                content = re.sub(
                    r"<enableRandomization>[^<]*</enableRandomization>",
                    f"<enableRandomization>{target}</enableRandomization>",
                    content)
            else:
                content = content.replace(
                    "</WLANProfile>",
                    f"  <MacRandomization>\r\n    <enableRandomization>{target}</enableRandomization>\r\n"
                    "  </MacRandomization>\r\n</WLANProfile>")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            # 优先写回所有用户配置（需管理员），失败退回当前用户
            for user_scope in ("user=all", "user=current"):
                result = self._run(["netsh", "wlan", "add", "profile",
                                    f"filename={path}", user_scope], timeout=20)
                if result.returncode == 0:
                    self.log(f"已将 WiFi “{ssid}” 的随机硬件地址设为{state}（重新连接后生效）。")
                    return True
            detail = ((result.stdout or "") + (result.stderr or "")).strip()
            self.log(f"修改 WLAN 配置文件失败（可能需要管理员权限）：{detail}")
            return False
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"修改随机硬件地址设置失败: {e}")
            return False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def disable_wlan_random_mac(self, ssid):
        """为指定 WLAN 配置文件关闭“随机硬件地址”。

        随机 MAC 每次重连都会变化，校园网认证把终端与 MAC 绑定，
        会导致反复掉线或被判定为新设备。
        """
        return self._set_wlan_randomization(ssid, False)

    # ---------- 校园 WiFi 连接决策链 ----------

    def ensure_wifi(self):
        """确保连接到校园 WiFi（交互式）。高级工具也可直接调用。

        决策链：
        1. 已连的 WiFi 命中关键字 -> 直接使用；
        2. 配置里记住的 WiFi（上次选择）-> 尝试直连；
        3. 扫描周围网络，按关键字筛选 -> 交给用户选择（可手动输入、可跳过）；
        4. 选中开放网络时自动创建配置文件再连接。
        连接成功后会把用户的选择写回配置，下次免问。
        """
        _, current = self.get_wifi_state()
        actions = []
        return self._pick_and_connect_wifi(current, actions)

    def _wifi_matches_keyword(self, ssid):
        keyword = (self.config.get("wifi_keyword") or "").strip().upper()
        return bool(ssid) and (not keyword or keyword in ssid.upper())

    def _pick_and_connect_wifi(self, current_ssid, actions):
        cfg = self.config

        # 1) 当前已连的 WiFi 就是校园网 -> 无需操作
        if self._wifi_matches_keyword(current_ssid):
            self.log(f"当前已连接无线网络 {current_ssid}。")
            return True

        # 2) 上次记住的 / 设置中配置的首选 WiFi -> 直接尝试
        target = (cfg.get("wifi_ssid") or "").strip()
        if target and target != current_ssid:
            self.log(f"正在连接无线网络 {target} ...")
            if self.connect_wifi(target):
                actions.append({"step": f"连接无线网络 {target}", "result": "success"})
                return True

        # 3) 扫描 -> 关键字筛选 -> 交用户选择
        self.log("正在扫描周围的无线网络...")
        networks = scan_wifi_networks()
        if not networks:
            self.log("未扫描到任何无线网络（请确认电脑带有无线网卡且 WLAN 功能已开启）。")
            return False
        candidates = filter_wifi_candidates(networks, cfg.get("wifi_keyword"))
        if not candidates:
            candidates = networks  # 全都不匹配也不开放时，列出全部供用户挑选
        if cfg.get("wifi_keyword"):
            self.log(f"已按关键字 “{cfg['wifi_keyword']}” 筛选出 {len(candidates)} 个候选网络。")

        choice = ""
        if self.interaction:
            choice = (self.interaction.pick_wifi(candidates, current_ssid) or "").strip()
        if not choice:
            self.log("已跳过 WiFi 选择。")
            return False

        # 4) 记住用户选择，下次免问
        if choice != target:
            cfg["wifi_ssid"] = choice
            try:
                save_config(cfg)
                self.log(f"已记住 WiFi 选择 {choice}（下次将自动连接）。")
            except OSError:
                pass

        net = next((n for n in candidates if n["ssid"] == choice), None)
        if net and is_open_network(net):
            # 开放网络未保存过配置时无法直连，先创建配置文件（幂等）
            self.log(f"正在为开放网络 {choice} 准备连接配置...")
            if create_open_wifi_profile(choice):
                record_revert_entry({"type": "profile", "ssid": choice})

        self.log(f"正在连接无线网络 {choice} ...")
        if self.connect_wifi(choice):
            actions.append({"step": f"连接无线网络 {choice}", "result": "success"})
            return True
        actions.append({"step": f"连接无线网络 {choice}", "result": "fail",
                        "detail": "无法自动连接，请手动连接后重试"})
        return False

    def _ensure_network(self, checks, actions):
        """确保存在可用网络连接；必要时交互式选择 WiFi。返回可用网卡列表。"""
        cfg = self.config
        netcards = self.get_enabled_physical_netcards_with_ipv4()
        if netcards and self.ping_host(cfg["gateway"], timeout=5, quiet=True):
            checks.append(self._check("adapter", "网络连接", "ok",
                                      detail="检测到可用连接：" + "、".join(netcards)))
            return netcards

        wlan_ok, current_ssid = self.get_wifi_state()
        if netcards and self._wifi_matches_keyword(current_ssid):
            # 已连着校园 WiFi 但网关暂时不通：交给后续 DHCP / 修复流程
            checks.append(self._check("adapter", "网络连接", "ok",
                                      detail="检测到可用连接：" + "、".join(netcards)))
            return netcards

        if wlan_ok:
            self.log("未检测到可用的校园网连接，将尝试连接校园无线网络...")
            if self._pick_and_connect_wifi(current_ssid, actions):
                time.sleep(3)
                netcards = self.get_enabled_physical_netcards_with_ipv4()

        if netcards:
            checks.append(self._check("adapter", "网络连接", "ok",
                                      detail="检测到可用连接：" + "、".join(netcards)))
        return netcards

    # ---------- 系统代理检测与修复（残留代理软件会导致登录后网页仍打不开） ----------

    def get_system_proxy(self):
        """读取当前用户的 Windows 系统代理设置（注册表），返回 dict。

        返回: {"enabled": bool, "server": str, "pac_url": str}
        注意：PAC（AutoConfigURL）即使 ProxyEnable=0 也视为代理开启。
        """
        info = {"enabled": False, "server": "", "pac_url": ""}
        if winreg is None:
            return info
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, winreg.KEY_READ)
            try:
                enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                info["enabled"] = bool(enable)
            except FileNotFoundError:
                pass
            try:
                info["server"], _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                pass
            try:
                info["pac_url"], _ = winreg.QueryValueEx(key, "AutoConfigURL")
                if info["pac_url"]:
                    info["enabled"] = True
            except FileNotFoundError:
                pass
            key.Close()
        except OSError as e:
            self.log(f"读取系统代理设置失败: {e}")
        return info

    def disable_system_proxy(self):
        """关闭当前用户的系统代理（清除 PAC），并通知系统立即生效。"""
        if winreg is None:
            return False
        # 修改前快照原始状态，供“撤销所有更改”还原
        snapshot = self.get_system_proxy()
        if snapshot["enabled"] or snapshot["pac_url"] or snapshot["server"]:
            record_revert_entry({"type": "proxy", "original": snapshot})
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        except OSError as e:
            self.log(f"关闭系统代理失败: {e}")
            return False
        self._refresh_internet_settings()
        return True

    @staticmethod
    def _refresh_internet_settings():
        """通过 InternetSetOption 通知系统代理设置已更改，立即生效（无需注销）。"""
        try:
            set_option = ctypes.windll.wininet.InternetSetOption
            set_option(None, 39, None, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
            set_option(None, 37, None, 0)  # INTERNET_OPTION_REFRESH
        except Exception:
            pass

    def reset_winhttp_proxy(self):
        """重置 WinHTTP 代理（影响系统服务级代理，需管理员权限）。"""
        original = self.get_winhttp_original()
        if original:
            record_revert_entry({"type": "winhttp", "original": original})
        result = self._run("netsh winhttp reset proxy")
        if result.returncode == 0:
            self.log("已重置 WinHTTP 代理。")
        else:
            self.log(f"重置 WinHTTP 代理失败（需要管理员权限）。错误: {result.stdout}\n{result.stderr}")
        return result.returncode == 0

    # ---------- 撤销所有更改（还原日志逆向恢复） ----------

    def get_dns_original(self, netcard):
        """读取网卡当前 DNS 配置：{"dhcp": bool, "servers": [...]}，供撤销时还原。"""
        result = self._run(["netsh", "interface", "ip", "show", "dnsservers",
                            f"name={netcard}"], timeout=20)
        if result.returncode != 0:
            return None
        text = result.stdout or ""
        if ("静态" in text) or ("static" in text.lower()):
            servers = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
            return {"dhcp": False, "servers": servers}
        if "dhcp" in text.lower():
            return {"dhcp": True, "servers": []}
        return {"dhcp": False, "servers": []}  # 未配置任何 DNS

    def get_address_original(self, netcard):
        """读取网卡当前 IPv4 地址配置，供撤销时还原。"""
        result = self._run(["netsh", "interface", "ip", "show", "addresses",
                            f"name={netcard}"], timeout=20)
        if result.returncode != 0:
            return None
        text = result.stdout or ""
        dhcp = bool(re.search(r"DHCP 已启用\s*:\s*是|DHCP Enabled\s*:\s*Yes", text, re.I))
        m_ip = re.search(r"(?:IP 地址|IP Address)\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})", text)
        if dhcp:
            return {"dhcp": True}
        if not m_ip:
            return None
        m_pf = re.search(r"(?:子网前缀长度|Subnet Prefix Length)\s*:\s*(\d{1,2})", text)
        m_gw = re.search(r"(?:默认网关|Default Gateway)\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})", text)
        return {"dhcp": False, "ip": m_ip.group(1),
                "prefix": int(m_pf.group(1)) if m_pf else 24,
                "gateway": m_gw.group(1) if m_gw else ""}

    def _record_network_original(self, netcard):
        """把网卡当前的 IP / DNS 配置记入还原日志（还原日志会自动去重，只保留最早记录）。"""
        addr = self.get_address_original(netcard)
        if addr:
            record_revert_entry({"type": "address", "card": netcard, "original": addr})
        dns = self.get_dns_original(netcard)
        if dns:
            record_revert_entry({"type": "dns", "card": netcard, "original": dns})

    def _restore_proxy(self, original):
        """把系统代理注册表恢复到记录的原始状态并通知系统刷新。"""
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_PATH, 0, winreg.KEY_SET_VALUE)
            if original.get("enabled"):
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                if original.get("server"):
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, original["server"])
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            if original.get("pac_url"):
                winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, original["pac_url"])
            winreg.CloseKey(key)
        except OSError as e:
            self.log(f"恢复系统代理设置失败: {e}")
            return False
        self._refresh_internet_settings()
        return True

    def get_winhttp_original(self):
        """读取 WinHTTP 代理原始状态，供撤销时还原。"""
        result = self._run("netsh winhttp show proxy", timeout=20)
        if result.returncode != 0:
            return None
        text = result.stdout or ""
        if ("直接访问" in text) or ("Direct access" in text):
            return {"direct": True}
        m_srv = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?)", text)
        if not m_srv:
            return None
        m_byp = re.search(r"(?:绕过列表|Bypass List)\s*[:：]\s*(.*)", text)
        return {"direct": False, "server": m_srv.group(1),
                "bypass": m_byp.group(1).strip() if m_byp else ""}

    def revert_all_changes(self):
        """撤销本工具做过的所有系统更改，恢复到修改前的状态。

        处理还原日志 revert_state.json 中的记录：重新启用被禁用的网卡、
        恢复 IP/DNS 原配置、还原系统代理、恢复随机 MAC 设置、删除本工具
        创建的 WiFi 配置文件。撤销失败的记录会保留，可再次尝试。
        """
        entries = load_revert_entries()
        actions = []
        if not entries:
            self.log("没有记录到需要撤销的更改，系统未被本工具修改过。")
            return actions
        self.log(f"共记录 {len(entries)} 项本工具所做的更改，正在逐一撤销...")
        remaining = []
        for entry in reversed(entries):
            etype = entry.get("type")
            ok, step = False, ""
            try:
                if etype == "adapter":
                    name = entry.get("card", "")
                    step = f"重新启用网卡 {name}"
                    ok = self._run(["netsh", "interface", "set", "interface",
                                    f"name={name}", "admin=enable"],
                                   timeout=30).returncode == 0
                elif etype == "dns":
                    card, o = entry.get("card", ""), entry.get("original", {})
                    if o.get("dhcp"):
                        step = f"将 {card} 的 DNS 恢复为 DHCP 自动获取"
                        ok = self._run(["netsh", "interface", "ip", "set", "dns",
                                        f"name={card}", "source=dhcp"],
                                       timeout=30).returncode == 0
                    else:
                        servers = o.get("servers", [])
                        step = f"恢复 {card} 的静态 DNS（{'、'.join(servers) if servers else '空'}）"
                        if servers:
                            ok = self._run(
                                ["netsh", "interface", "ip", "set", "dns",
                                 f"name={card}", "source=static",
                                 f"addr={servers[0]}", "register=PRIMARY"],
                                timeout=30).returncode == 0
                            for i, s in enumerate(servers[1:], start=2):
                                self._run(["netsh", "interface", "ip", "add", "dns",
                                           f"name={card}", f"addr={s}", f"index={i}"],
                                          timeout=30)
                        else:
                            ok = self._run(["netsh", "interface", "ip", "set", "dns",
                                            f"name={card}", "source=static", "addr=none"],
                                           timeout=30).returncode == 0
                elif etype == "address":
                    card, o = entry.get("card", ""), entry.get("original", {})
                    if o.get("dhcp", True):
                        step = f"将 {card} 的 IP 地址恢复为 DHCP 自动获取"
                        ok = self._run(["netsh", "interface", "ip", "set", "address",
                                        f"name={card}", "source=dhcp"],
                                       timeout=30).returncode == 0
                    else:
                        ip = o.get("ip", "")
                        step = f"恢复 {card} 的静态 IP（{ip}）"
                        mask = prefix_to_mask(o.get("prefix", 24))
                        gw = o.get("gateway", "")
                        cmd = ["netsh", "interface", "ip", "set", "address",
                               f"name={card}", "source=static",
                               f"addr={ip}", f"mask={mask}",
                               f"gateway={gw if gw else 'none'}"]
                        ok = self._run(cmd, timeout=30).returncode == 0
                elif etype == "proxy":
                    step = "恢复系统代理原设置"
                    ok = self._restore_proxy(entry.get("original", {}))
                elif etype == "winhttp":
                    o = entry.get("original", {})
                    if o.get("direct"):
                        step = "恢复 WinHTTP 代理为直接访问"
                        ok = self._run("netsh winhttp reset proxy", timeout=30).returncode == 0
                    elif o.get("server"):
                        step = f"恢复 WinHTTP 代理（{o['server']}）"
                        proxy_cmd = ["netsh", "winhttp", "set", "proxy",
                                     f"proxy-server={o['server']}"]
                        if o.get("bypass"):
                            proxy_cmd.append(f"bypass-list={o['bypass']}")
                        ok = self._run(proxy_cmd, timeout=30).returncode == 0
                    else:
                        step = "恢复 WinHTTP 代理（原始状态未知，请手动检查）"
                elif etype == "randommac":
                    ssid = entry.get("ssid", "")
                    step = f"恢复 WiFi “{ssid}” 的随机 MAC 设置"
                    ok = self._set_wlan_randomization(ssid, True)
                elif etype == "profile":
                    ssid = entry.get("ssid", "")
                    step = f"删除本工具创建的 WiFi 配置文件 {ssid}"
                    ok = self._run(["netsh", "wlan", "delete", "profile",
                                    f"name={ssid}"], timeout=20).returncode == 0
            except Exception as e:  # 单项失败不影响其余撤销
                self.log(f"撤销“{step or etype}”时出错: {e}")
            if ok:
                self.log(f"已撤销：{step}。")
                actions.append({"step": f"撤销 - {step}", "result": "success"})
            else:
                self.log(f"撤销失败：{step}。可再次尝试，或按提示手动恢复。")
                actions.append({"step": f"撤销 - {step}", "result": "fail"})
                remaining.append(entry)
        save_revert_entries(remaining)
        if remaining:
            self.log(f"撤销完成，{len(remaining)} 项未能恢复（已保留记录，可再次尝试）。")
        else:
            self.log("所有更改已撤销，系统已恢复到本工具修改前的状态。")
        return actions

    # ---------- 认证状态查询（drcom chkstatus 接口） ----------

    @staticmethod
    def _extract_json_object(text):
        """从 JSONP 响应（如 dr1003({...})）中精确提取第一个 JSON 对象。

        用括号深度计数而非正则贪婪匹配，避免响应含多个 {} 时取错范围。
        返回匹配到的 JSON 字符串；找不到返回 None。
        """
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return None

    def check_auth_status(self):
        """查询网关在线状态接口，读取当前认证账号与运营商线路。

        drcom 固件通常提供 chkstatus JSONP 接口；解析失败不影响主流程
        （登录成功的最终判定仍以外网 ping 为准），仅用于“读取相关信息”。
        返回: {"online": bool|None, "account": str, "carrier": str, "error": str}
        """
        result = {"online": None, "account": "", "carrier": "", "error": ""}
        status_url = self.config.get("status_url") or f"http://{self.config['gateway']}/drcom/chkstatus"
        session = requests.Session()
        session.trust_env = False  # 绕过系统代理直连网关
        try:
            dp = dict(self.config.get("drcom_params") or {})
            resp = session.get(
                status_url,
                params=[("callback", dp.get("callback", "dr1003")),
                        ("jsVersion", dp.get("jsVersion", "4.2")),
                        ("v", str(random.randint(1000, 9999)))],
                timeout=self.config["login_timeout"],
            )
        except (Timeout, RequestException) as e:
            result["error"] = str(e)
            return result
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        match = self._extract_json_object(resp.text)  # 剥掉 JSONP 外壳（精确括号匹配）
        if not match:
            result["error"] = "响应格式无法识别"
            return result
        try:
            data = json.loads(match)
        except ValueError:
            result["error"] = "JSON 解析失败"
            return result

        for key in ("uid", "account", "user", "DDDDD", "username"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                result["account"] = value.strip()
                break
        if "@" in result["account"]:
            suffix = result["account"].rsplit("@", 1)[1].lower()
            if suffix in CARRIER_NAMES:
                result["carrier"] = suffix

        # 不同固件在线字段不一致，宽松识别；识别不了则保持 None（以外网 ping 为准）
        for key in ("is_authorized", "online", "is_login", "islogon"):
            if key in data:
                result["online"] = str(data[key]).strip().lower() in ("yes", "true", "1", "ok")
                break
        return result

    def _remember_auth_info(self, account="", carrier=""):
        """把认证页面登录学到的账号/运营商写入默认配置，方便下次使用。"""
        changed = False
        if account and account != self.config.get("last_account"):
            self.config["last_account"] = account
            changed = True
        if carrier and carrier != self.config.get("carrier"):
            self.config["carrier"] = carrier
            changed = True
        if changed:
            try:
                save_config(self.config)
                self.log("已将本次认证使用的账号与运营商线路保存到默认配置。")
            except OSError:
                pass

    # ---------- 校园网认证 ----------

    def login(self, student_id, password, carrier=None):
        """登录校园网认证服务器，返回是否成功。

        :param carrier: 运营商代码 cmcc/ctcc/cucc；不传则使用交互选择或配置默认值。
        """
        carrier = (carrier or self.carrier_override or self.config["carrier"] or "cmcc").strip().lower()
        if carrier not in CARRIER_NAMES:
            self.log(f"未知的运营商标识 “{carrier}”，已回退为中国移动（cmcc）。")
            carrier = "cmcc"
        self.log(f"正在使用 {CARRIER_NAMES[carrier]} 线路登录校园网...")

        # Host / Referer 根据认证地址自动推导，避免与配置不一致
        netloc = urlparse(self.config["auth_url"]).netloc or self.config["gateway"]
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Referer": f"http://{netloc}/a79.htm",
            "User-Agent": random.choice(USER_AGENTS),
        }

        # drcom 协议参数从配置读取（固件升级时可在 config.json 中调整）
        dp = dict(self.config.get("drcom_params") or {})
        params = [
            ("callback", dp.get("callback", "dr1003")),
            ("DDDDD", f"{student_id}@{carrier}"),
            ("upass", password),
            ("0MKKey", dp.get("0MKKey", "123456")),
            ("R1", dp.get("R1", "0")),
            ("R2", dp.get("R2", "")),
            ("R3", dp.get("R3", "0")),
            ("R6", dp.get("R6", "0")),
            ("para", dp.get("para", "00")),
            ("v6ip", dp.get("v6ip", "")),
            ("terminal_type", dp.get("terminal_type", "1")),
            ("lang", dp.get("lang", "zh-cn")),
            ("jsVersion", dp.get("jsVersion", "4.2")),
            ("v", dp.get("v", "7081")),
            ("lang", "zh"),  # 保留原始双 lang 参数（drcom 兼容）
        ]

        try:
            session = requests.Session()
            session.trust_env = False  # 绕过系统代理，确保直连校内网关
            response = session.get(
                self.config["auth_url"], params=params,
                headers=headers, timeout=self.config["login_timeout"],
            )
        except Timeout:
            self.log("认证服务器连接超时。")
            time.sleep(5)
            return False
        except RequestException as e:
            self.log(f"认证请求失败: {e}")
            time.sleep(5)
            return False

        if response.status_code != 200:
            self.log(f"认证请求失败，HTTP 状态码: {response.status_code}")
            time.sleep(5)
            return False

        # 解析 drcom 返回的 JSONP 响应，提取 result 字段判断登录结果。
        # drcom 固件通常返回 dr1003({"result":1,"msg":"..."}):
        #   result=1 表示登录成功，result=0 表示失败，msg 为失败原因。
        # 若无法解析（固件差异），回退到 loadErrorPrompt 启发式判断。
        login_ok = None
        error_msg = ""
        json_str = self._extract_json_object(response.text)
        if json_str:
            try:
                data = json.loads(json_str)
                # 不同固件成功字段名可能不同，逐一尝试
                for key in ("result", "ret", "success", "code"):
                    if key in data:
                        val = str(data[key]).strip().lower()
                        login_ok = val in ("1", "true", "yes", "ok", "success")
                        if not login_ok:
                            error_msg = str(data.get("msg") or data.get("message") or "未知错误")
                        break
            except (ValueError, TypeError):
                pass  # JSON 解析失败，回退到启发式判断

        if login_ok is None:
            # 未能解析 result 字段：检查旧固件的 loadErrorPrompt 失败标记
            if "loadErrorPrompt" in response.text:
                login_ok = False
                error_msg = "请检查账号密码或者手机是否欠费"
            else:
                login_ok = True  # 旧固件无明确失败标记时保守判定为成功

        if not login_ok:
            self.log(f"登录失败：{error_msg or '请检查账号密码或者手机是否欠费。'}")
            return False

        self.log("登录成功。")
        return True

    def _get_credentials(self):
        """通过交互对象获取学号密码；未提供交互或用户取消时返回 None。

        交互对象也可能返回 dict（如 {"portal_login": True, ...}），
        表示用户已通过认证页面完成登录，主流程会跳过重复登录。
        无论哪种途径，成功获取的账号与运营商都会被记住。
        """
        if self._credentials_declined:
            return None
        if self.interaction is None:
            self.log("未提供用户交互方式（interaction 为空），跳过登录环节。")
            return None
        try:
            creds = self.interaction.get_credentials(
                last_account=self.config.get("last_account", ""),
                prefill_carrier=self.carrier_override or self.config.get("carrier", "cmcc"),
            )
        except Exception as e:
            self.log(f"获取账号信息失败: {e}")
            return None
        if creds is None:
            self.log("已取消登录。")
            self._credentials_declined = True
            return None
        if isinstance(creds, dict):  # 特殊指令（如认证页面登录完成）
            return creds

        sid, pwd, carrier = (list(creds) + ["", "", ""])[:3]
        sid, pwd, carrier = (sid or "").strip(), (pwd or "").strip(), (carrier or "").strip()
        if not sid or not pwd:
            self.log("已取消登录（学号或密码为空）。")
            self._credentials_declined = True
            return None
        if carrier in CARRIER_NAMES and carrier != self.config.get("carrier"):
            self.carrier_override = carrier  # 用户选择的线路优先于配置
        return sid, pwd

    # ---------- 报告结构（供 UI 渲染） ----------

    @staticmethod
    def _check(key, title, status, detail="", problem="", fix=""):
        """构造单条检测结果。status: ok / fail / warn / skip"""
        return {"key": key, "title": title, "status": status,
                "detail": detail, "problem": problem, "fix": fix}

    @staticmethod
    def _report(ok, checks, actions):
        issues = [c for c in checks if c["status"] in ("fail", "warn")]
        if ok:
            summary = "网络一切正常"
        elif issues:
            summary = f"发现 {len(issues)} 个问题"
        else:
            summary = "未能完全修复，请查看各项目详情"
        return {"ok": ok, "summary": summary, "checks": checks, "actions": actions}

    # ---------- 一键检测（仅检测，不修改系统） ----------

    def diagnose(self):
        """逐层检测：网卡 -> 外网 -> WiFi -> 内网 -> 认证 -> DNS -> 代理，返回结构化报告。"""
        cfg = self.config
        checks = []
        self.log("开始网络诊断...")

        # 硬件故障判定：已连接（网线/WiFi）但拿不到地址，软件层面无法修复
        states = self.get_physical_adapter_ip_states()
        netcards = [s["name"] for s in states if s["ipv4"]]
        if not netcards:
            link_local = [s["name"] for s in states if s["link_local"]]
            if link_local:
                checks.append(self._check(
                    "adapter", "网络连接", "fail",
                    detail=f"{'、'.join(link_local)} 仅获取到 169.254.x.x 链路本地地址",
                    problem="网卡已连接，但只获取到 169.254.x.x 链路本地地址"
                            "（Windows 在始终无法从校园网获取 IP 时自动分配的备用地址），"
                            "说明校园网接入设备没有响应，属于校园网硬件故障，"
                            "本工具无法通过软件方式修复",
                    fix="可先尝试“一键修复”让电脑自动重新获取 IP；若无效请检查网线是否插稳、"
                        "换一根网线或换一个墙上网口试试，仍无效请联系校园网网络管理员报修"))
                self.log("诊断完成：检测到 169.254.x.x 链路本地地址，判定为校园网硬件故障。")
                return self._report(False, checks, [])
            connected = [s["name"] for s in states if s["connected"]]
            if connected:
                checks.append(self._check(
                    "adapter", "网络连接", "fail",
                    detail=f"{'、'.join(connected)} 已连接但未获取到 IP 地址",
                    problem="网络已连接（网线已插好 / WiFi 已连上），但始终未获取到 IP 地址，"
                            "说明校园网接入设备没有响应，属于校园网硬件故障，"
                            "本工具无法通过软件方式修复",
                    fix="可先尝试“一键修复”让电脑自动重新获取 IP；若无效请检查网线是否插稳、"
                        "换一根网线或换一个墙上网口试试，仍无效请联系校园网网络管理员报修"))
                self.log("诊断完成：网络已连接但未获取到 IP 地址，判定为校园网硬件故障。")
                return self._report(False, checks, [])
            checks.append(self._check(
                "adapter", "网络连接", "fail",
                problem="没有可用的网络连接（未插网线或未连接 WiFi）",
                fix="插入网线，或使用“一键修复”（会扫描并帮你连接校园 WiFi）"))
            self.log("诊断完成：未找到可用网络连接。")
            return self._report(False, checks, [])
        checks.append(self._check("adapter", "网络连接", "ok",
                                  detail="检测到可用连接：" + "、".join(netcards)))

        # 外网连通性快速检测：一开始就 ping 一个公网地址，给用户直观的"网络是否正常"反馈
        self.log(f"正在检测外网连通性（{cfg['public_test_host']}）...")
        external_ok = self.ping_host(cfg["public_test_host"])
        if external_ok:
            checks.append(self._check("external", "外网连通", "ok",
                                      detail=f"网络正常（{cfg['public_test_host']} 可达）"))
        else:
            checks.append(self._check("external", "外网连通", "warn",
                                      detail=f"暂时无法访问 {cfg['public_test_host']}",
                                      problem="无法访问公共互联网",
                                      fix="校园网环境可能是未认证，请继续查看下方认证检测结果；"
                                          "非校园网环境请检查网络连接"))

        # WiFi 连接状态（信息性：有线用户未连 WiFi 不算故障）
        wlan = self.get_wlan_info()
        wlan_ok, current_ssid = wlan["ok"], wlan["ssid"]
        keyword = (cfg.get("wifi_keyword") or "").strip()
        if current_ssid:
            if not keyword or keyword.upper() in current_ssid.upper():
                checks.append(self._check("wifi", "校园 WiFi", "ok",
                                          detail=f"已连接 {current_ssid}（命中关键字“{keyword}”）"))
            else:
                checks.append(self._check(
                    "wifi", "校园 WiFi", "warn",
                    detail=f"当前连接的是 {current_ssid}（名称不含关键字“{keyword}”，可能不是校园网）"))
        else:
            checks.append(self._check(
                "wifi", "校园 WiFi", "skip",
                detail="未连接任何 WiFi" if wlan_ok else "未检测到可用无线网卡"))

        # 多网卡同时连接校园网：认证系统限制终端数量时会互相挤下线（反复掉线）
        self.log("正在检测是否存在多网卡同时连接校园网...")
        campus_cards = self.find_campus_connected_adapters()
        if len(campus_cards) >= 2:
            checks.append(self._check(
                "multinic", "多网卡冲突", "warn",
                detail="同时连接校园网的网卡：" + "、".join(campus_cards),
                problem="多张网卡同时连着校园网，认证系统可能将其判定为多台终端；"
                        "若账号有终端数量限制，会互相挤下线（表现为反复掉线）",
                fix="使用“一键修复”，选择保留一张网卡（其余网卡将被暂时禁用，"
                    "之后可在“控制面板 → 网络连接”中重新开启）"))
        elif len(campus_cards) == 1:
            checks.append(self._check("multinic", "多网卡冲突", "ok",
                                      detail=f"仅 {campus_cards[0]} 连接校园网，无冲突"))
        else:
            checks.append(self._check("multinic", "多网卡冲突", "skip",
                                      detail="网关不可达，无法判定各网卡连接状态"))

        # WiFi 随机 MAC：每次重连 MAC 变化，认证绑定 MAC 时会反复要求重新认证/掉线
        if current_ssid:
            if not wlan.get("mac"):
                checks.append(self._check("randommac", "WiFi 随机 MAC", "skip",
                                          detail="无法读取网卡 MAC 地址，跳过"))
            elif is_random_mac(wlan["mac"]):
                checks.append(self._check(
                    "randommac", "WiFi 随机 MAC", "warn",
                    detail=f"{wlan['name']} 当前 MAC：{format_mac(wlan['mac'])}",
                    problem="WLAN 开启了“随机硬件地址”，每次重连 MAC 都会变化；"
                            "校园网认证把终端与 MAC 绑定，会导致反复掉线或被要求重新认证",
                    fix="使用“一键修复”自动为当前校园 WiFi 配置文件关闭随机 MAC；"
                        "也可到 设置 → 网络和 Internet → WLAN → 管理已知网络 手动关闭"))
            else:
                checks.append(self._check("randommac", "WiFi 随机 MAC", "ok",
                                          detail="使用固定物理 MAC，无随机 MAC 掉线风险"))
        else:
            checks.append(self._check("randommac", "WiFi 随机 MAC", "skip",
                                      detail="未连接 WiFi，跳过"))

        # WiFi 信号强度：校园网一般每间宿舍部署一个 AP，信号弱说明连到隔壁宿舍 AP
        if current_ssid:
            sig = wlan.get("signal", -100)
            if sig == -100:
                checks.append(self._check("signal", "WiFi 信号强度", "skip",
                                          detail="无法读取信号强度"))
            elif sig >= -60:
                checks.append(self._check("signal", "WiFi 信号强度", "ok",
                                          detail=f"信号良好（{sig}dBm），连接的是附近 AP"))
            elif sig >= -75:
                checks.append(self._check("signal", "WiFi 信号强度", "warn",
                                          detail=f"信号一般（{sig}dBm），可能离 AP 较远",
                                          problem="当前 WiFi 信号偏弱，可能连接的是较远的 AP（如隔壁宿舍的 AP）。"
                                                  "本宿舍 AP 故障或过载时会导致此现象，"
                                                  "信号弱可能引起网速慢、延迟高或掉线",
                                          fix="检查本宿舍 AP 是否正常工作（指示灯是否亮）；"
                                              "可尝试关闭再开启 WiFi 重新连接最近的 AP；"
                                              "如本宿舍 AP 确认故障，请联系网络管理员报修"))
            else:
                checks.append(self._check("signal", "WiFi 信号强度", "warn",
                                          detail=f"信号较弱（{sig}dBm），连接的可能是远端 AP",
                                          problem="当前 WiFi 信号很弱，很可能连接的是隔壁宿舍或更远的 AP。"
                                                  "本宿舍 AP 可能故障或被关闭，"
                                                  "信号弱会导致网速慢、延迟高、容易掉线",
                                          fix="尝试关闭 WiFi 再重新开启，让设备重新连接最近的 AP；"
                                              "如反复出现信号弱，请联系网络管理员检查本宿舍 AP"))
        else:
            checks.append(self._check("signal", "WiFi 信号强度", "skip",
                                      detail="未连接 WiFi，跳过"))

        self.log(f"正在检测内网连通性（网关 {cfg['gateway']}）...")
        intranet_ok = self.ping_host(cfg["gateway"])
        non_campus = not intranet_ok
        if intranet_ok:
            checks.append(self._check("intranet", "校园网内网", "ok",
                                      detail=f"已连通网关 {cfg['gateway']}"))
        else:
            # 网关不可达 → 当前并非校园网环境（可能是家庭宽带 / 手机热点 / 公共 WiFi）
            checks.append(self._check(
                "intranet", "校园网内网", "warn",
                problem=f"无法连通校园网网关 {cfg['gateway']}，当前很可能并非校园网环境",
                fix="本工具专为校园网设计，非校园网环境下请勿点击“一键修复”，"
                    "以免修改网络配置导致当前网络无法上网。"
                    "如需检测 DNS / 代理等通用设置，可参考下方检测结果。"))

        auth_ok = False
        if intranet_ok:
            # 复用前面已检测的外网连通结果，不重复 ping
            auth_ok = external_ok
            if auth_ok:
                checks.append(self._check("auth", "校园网认证", "ok",
                                          detail="认证有效，可正常访问外网"))
            else:
                checks.append(self._check(
                    "auth", "校园网认证", "fail",
                    problem="可访问内网，但无法访问外网（认证已失效或未认证）",
                    fix="使用“一键修复”并输入学号密码重新认证（注意选择运营商线路）"))
        else:
            checks.append(self._check(
                "auth", "校园网认证", "skip",
                detail="非校园网环境，无法检测校园网认证状态"))

        # DNS 检测：非校园网环境下也需要检测（用户可能有 DNS 配置问题）
        self.log(f"正在检测域名解析（{cfg['test_domain']}）...")
        if self.ping_host(cfg["test_domain"]):
            checks.append(self._check("dns", "域名解析", "ok",
                                      detail=f"{cfg['test_domain']} 解析正常"))
        else:
            checks.append(self._check(
                "dns", "域名解析", "warn" if non_campus else "fail",
                problem=f"无法解析 {cfg['test_domain']}（DNS 服务异常或配置错误）",
                fix="非校园网环境下请手动检查 DNS 设置；校园网环境可使用“一键修复”"
                    "（自动切换公共 DNS / 校内 DNS / DHCP）"))

        # 系统代理：残留代理软件会导致“登录成功但浏览器打不开网页”
        self.log("正在检测系统代理设置...")
        proxy = self.get_system_proxy()
        if not proxy["enabled"]:
            checks.append(self._check("proxy", "系统代理", "ok",
                                      detail="未开启系统代理，不会影响网页访问"))
        else:
            source = proxy.get("pac_url") or proxy.get("server") or "未知"
            checks.append(self._check(
                "proxy", "系统代理", "warn",
                problem=f"检测到系统代理已开启（{source}），多为此前代理/加速软件残留，"
                        f"会导致浏览器无法打开网页",
                fix="校园网环境可使用“一键修复”自动关闭；非校园网环境请到 "
                    "Windows 设置 → 网络和 Internet → 代理 中手动关闭"))

        # 非校园网环境：ok 恒为 False，并在报告中标记，前端会显示强烈警告并禁用修复
        if non_campus:
            ok = False
        else:
            ok = not any(c["status"] in ("fail", "warn") for c in checks)
        n_issue = len([c for c in checks if c["status"] in ("fail", "warn")])
        if non_campus:
            if external_ok:
                self.log("诊断完成：网络正常，但当前不在校园网环境，已禁用一键修复。")
            else:
                self.log("诊断完成：当前并非校园网环境，已禁用一键修复，仅展示 DNS / 代理等通用检测结果。")
        else:
            self.log("诊断完成：" + ("网络一切正常。" if ok else f"发现 {n_issue} 个问题，可点击“一键修复”。"))
        report = self._report(ok, checks, [])
        report["non_campus"] = non_campus
        report["external_ok"] = external_ok
        return report

    # ---------- 一键修复 ----------

    def run_fix(self):
        """检测并逐项修复：网络连接(WiFi) -> 内网 -> 认证 -> DNS，返回结构化报告。

        需要“选择 WiFi / 输入账号密码 / 选运营商”等环节会通过 Interaction 询问用户，
        用户跳过的环节自动降级为对应的手动指引，不会中断整个流程。
        """
        cfg = self.config
        self._credentials_declined = False
        checks, actions = [], []
        self.log("开始一键修复...")

        # —— 前置检查：必须在校园网环境下才能修复 ——
        # 非校园网环境（家庭宽带 / 手机热点等）下执行修复会修改网络配置，
        # 可能导致当前网络无法上网，因此直接拒绝并给出明确警告。
        if not self.ping_host(cfg["gateway"], timeout=5, quiet=True):
            # 网关不可达要区分两种情况：
            # 1) 真·非校园网（已有正常 IP、也没连校园 WiFi，如家庭宽带/手机热点）
            #    → 拒绝修复，避免改坏当前网络；
            # 2) 已连校园 WiFi（SSID 命中关键字）或链路已连接但没拿到正常 IP
            #    （169.254 / 无 IP，即 DHCP 失败）→ 属于校园网内故障，放行给
            #    后续 _ensure_network / DHCP 重新获取流程处理。否则会把
            #    “连着宿舍 WiFi 但 DHCP 失败”误判成“非校园网环境”，既报错
            #    警告又跳过了本可恢复网络的 DHCP 修复。
            wlan_info = self.get_wlan_info()
            on_campus_wifi = self._wifi_matches_keyword(wlan_info.get("ssid", ""))
            link_trouble = any(s.get("connected") and not s.get("ipv4")
                               for s in self.get_physical_adapter_ip_states())
            if not on_campus_wifi and not link_trouble:
                self.log(f"无法连通校园网网关 {cfg['gateway']}，判定当前并非校园网环境。")
                self.log("为避免修改网络配置导致当前网络无法上网，已中止一键修复。")
                checks.append(self._check(
                    "intranet", "校园网内网", "fail",
                    problem=f"无法连通校园网网关 {cfg['gateway']}，当前并非校园网环境",
                    fix="请连接到校园网（宿舍 WiFi / 校园网线）后再使用一键修复；"
                        "当前网络的 DNS / 代理问题可使用“一键检测”查看并手动处理。"))
                report = self._report(False, checks, [])
                report["non_campus"] = True
                return report
            if on_campus_wifi:
                self.log(f"已连接校园 WiFi（{wlan_info['ssid']}）但网关暂时不可达，"
                         "将尝试重新获取 IP 后继续修复。")
            else:
                self.log("网络已连接但未获取到有效 IP（DHCP 可能失败），"
                         "将尝试重新获取 IP 后继续修复。")

        check_proxy = self._check("proxy", "系统代理", "skip", detail="待检测")

        # —— 第 0 步：系统代理（残留代理软件会导致登录后浏览器仍打不开网页） ——
        proxy = self.get_system_proxy()
        if not proxy["enabled"]:
            check_proxy.update(status="ok", detail="未开启系统代理", problem="", fix="")
        else:
            source = proxy.get("pac_url") or proxy.get("server") or "未知"
            self.log(f"检测到系统代理已开启（{source}），正在自动关闭...")
            if self.disable_system_proxy():
                check_proxy.update(status="ok", problem="", fix="",
                                   detail=f"检测到残留系统代理，已自动关闭（原代理：{source}）")
                actions.append({"step": "关闭系统代理", "result": "success", "detail": f"原代理：{source}"})
            else:
                check_proxy.update(status="warn",
                                   problem=f"系统代理已开启（{source}），会导致登录后网页仍无法打开",
                                   fix="请在 Windows 设置 → 网络和 Internet → 代理 中手动关闭后重新修复")
                actions.append({"step": "关闭系统代理", "result": "fail",
                                "detail": "自动关闭失败，请按提示手动关闭"})

        # —— 第 1 步：确保存在可用网络连接（必要时扫描并让用户选择校园 WiFi） ——
        netcards = self._ensure_network(checks, actions)
        if not netcards:
            checks.append(self._check(
                "adapter", "网络连接", "fail",
                problem="没有可用的网络连接（未插网线或未连接 WiFi）",
                fix="请插入网线，或手动连接校园 WiFi（可参考诊断出的候选网络）后重新修复"))
            self.log("修复结束：未找到可用网络连接。")
            checks.append(check_proxy)
            return self._report(False, checks, actions)

        # —— 第 1.5 步：多网卡冲突（认证终端数量限制会导致互相挤下线） ——
        check_multinic = self._check("multinic", "多网卡冲突", "skip", detail="待检测")
        self.log("正在检测是否存在多网卡同时连接校园网...")
        campus_cards = self.find_campus_connected_adapters()
        if len(campus_cards) >= 2:
            self.log(f"检测到 {len(campus_cards)} 张网卡同时连接校园网：{'、'.join(campus_cards)}。")
            keep = self.interaction.pick_adapter(campus_cards) if self.interaction else ""
            if keep and keep in campus_cards:
                disabled, failed = [], []
                for card in campus_cards:
                    if card == keep:
                        continue
                    result = self._run(["netsh", "interface", "set", "interface",
                                        f"name={card}", "admin=disable"], timeout=30)
                    if result.returncode == 0:
                        disabled.append(card)
                        record_revert_entry({"type": "adapter", "card": card})
                        self.log(f"已暂时禁用网卡 {card}（如需恢复：控制面板 → 网络连接 中右键启用）。")
                    else:
                        failed.append(card)
                        self.log(f"禁用网卡 {card} 失败（需要管理员权限）。")
                if disabled and not failed:
                    actions.append({"step": f"保留网卡 {keep}，禁用 {'、'.join(disabled)}", "result": "success"})
                    check_multinic.update(status="ok", problem="", fix="",
                                          detail=f"已保留 {keep}，其余网卡已暂时禁用")
                else:
                    actions.append({"step": "禁用多余网卡", "result": "fail",
                                    "detail": f"禁用失败：{'、'.join(failed) or '无操作'}"})
                    check_multinic.update(
                        status="warn",
                        problem="多张网卡同时连接校园网，可能因认证终端数量限制互相挤下线",
                        fix="关闭程序后右键“以管理员身份运行”重新修复；或到 控制面板 → 网络连接 手动禁用多余网卡")
                netcards = self.get_enabled_physical_netcards_with_ipv4()
            else:
                self.log("已跳过多网卡处理。")
                actions.append({"step": "处理多网卡冲突", "result": "skip", "detail": "用户跳过"})
                check_multinic.update(
                    status="warn",
                    problem=f"多张网卡（{'、'.join(campus_cards)}）同时连接校园网，可能互相挤下线",
                    fix="手动只保留一张网卡连接校园网，禁用或断开其余网卡")
        else:
            check_multinic.update(status="ok", detail="未检测到多网卡同时连接校园网")
        checks.append(check_multinic)

        # —— 第 1.6 步：WiFi 随机 MAC（重连换 MAC 会被认证判定为新终端，导致反复掉线） ——
        check_randmac = self._check("randommac", "WiFi 随机 MAC", "skip", detail="待检测")
        wlan = self.get_wlan_info()
        if wlan["ssid"] and self._wifi_matches_keyword(wlan["ssid"]):
            if not wlan.get("mac"):
                check_randmac.update(status="skip", detail="无法读取网卡 MAC 地址，跳过")
            elif is_random_mac(wlan["mac"]):
                self.log(f"WLAN（{wlan['name']}）正在使用随机 MAC（{format_mac(wlan['mac'])}），"
                         f"正在为 WiFi “{wlan['ssid']}” 关闭随机硬件地址...")
                if self.disable_wlan_random_mac(wlan["ssid"]):
                    record_revert_entry({"type": "randommac", "ssid": wlan["ssid"]})
                    actions.append({"step": f"为 WiFi “{wlan['ssid']}” 关闭随机 MAC",
                                    "result": "success", "detail": "重新连接 WiFi 后生效"})
                    check_randmac.update(status="ok", problem="", fix="",
                                         detail="已为当前校园 WiFi 关闭随机硬件地址")
                else:
                    actions.append({"step": "关闭 WiFi 随机 MAC", "result": "fail",
                                    "detail": "自动修改 WLAN 配置文件失败"})
                    check_randmac.update(
                        status="warn",
                        problem="WLAN 开启了“随机硬件地址”，每次重连 MAC 变化会被认证判定为新终端，导致反复掉线",
                        fix="到 设置 → 网络和 Internet → WLAN → 管理已知网络 → 选择当前 WiFi → 关闭“随机硬件地址”")
            else:
                check_randmac.update(status="ok", detail="使用固定物理 MAC，无随机 MAC 掉线风险")
        else:
            check_randmac.update(status="skip", detail="未连接校园 WiFi，跳过")
        checks.append(check_randmac)

        check_intranet = self._check("intranet", "校园网内网", "skip", detail="待检测")
        check_auth = self._check("auth", "校园网认证", "skip", detail="待检测")
        check_dns = self._check("dns", "域名解析", "skip", detail="待检测")
        checks.extend([check_intranet, check_auth, check_dns, check_proxy])

        fixed = False
        for card in netcards:
            self.log(f"正在通过 {card} 进行修复...")

            # —— 第 2 步：内网连通性 ——
            if self.ping_host(cfg["gateway"]):
                self.log("内部网络连接正常。")
                check_intranet.update(status="ok", problem="", fix="",
                                      detail=f"已连通网关 {cfg['gateway']}（网卡：{card}）")
            else:
                self.log(f"无法连接内网，正在将 {card} 设置为 DHCP 并重新获取 IP/DNS...")
                self._record_network_original(card)
                self.set_dhcp_and_renew(card)
                if self.ping_host(cfg["gateway"]):
                    actions.append({"step": f"将 {card} 恢复为 DHCP 并重新获取 IP", "result": "success"})
                    check_intranet.update(status="ok", problem="", fix="",
                                          detail="恢复 DHCP 后内网已恢复连通")
                else:
                    actions.append({"step": f"将 {card} 恢复为 DHCP 并重新获取 IP", "result": "fail",
                                    "detail": "内网仍无法连通，可能为校内网络或端口故障"})
                    check_intranet.update(status="fail",
                                          problem=f"无法连通校园网网关 {cfg['gateway']}",
                                          fix="已尝试恢复 DHCP 仍未解决，请检查网线/WiFi 信号，或联系网络管理员")
                    continue

            # —— 第 3 步：校园网认证（外网） ——
            if self.ping_host(cfg["public_test_host"]):
                self.log("外部网络连接正常，校园网认证有效。")
                check_auth.update(status="ok", problem="", fix="",
                                  detail="认证有效，可正常访问外网")
            else:
                self.log("无法访问外网，需要登录校园网认证。")
                creds = self._get_credentials()
                auth_ok = False
                if creds is None:
                    actions.append({"step": "登录校园网认证", "result": "skip",
                                    "detail": "未提供学号密码，已跳过认证"})
                    check_auth.update(status="fail",
                                      problem="校园网认证已失效或未认证",
                                      fix="再次点击“一键修复”，输入学号密码或选择“打开认证页面登录”")
                elif isinstance(creds, dict) and creds.get("portal_login"):
                    # 用户已在弹出的认证页面中完成登录，无需重复调用 login
                    self.log("已通过认证页面完成登录。")
                    if creds.get("account"):
                        self.log(f"认证账号：{creds['account']}")
                    self._remember_auth_info(creds.get("account", ""), creds.get("carrier", ""))
                    time.sleep(2)
                    auth_ok = self.ping_host(cfg["public_test_host"])
                    if auth_ok:
                        actions.append({"step": "通过认证页面完成登录", "result": "success"})
                        check_auth.update(status="ok", problem="", fix="",
                                          detail="认证成功，可正常访问外网")
                    else:
                        actions.append({"step": "通过认证页面完成登录", "result": "fail",
                                        "detail": "登录后仍无法访问外网"})
                        check_auth.update(status="fail",
                                          problem="认证后仍无法访问外网",
                                          fix="请确认账号是否欠费/在线设备超限，或联系网络管理员")
                else:
                    student_id, password = creds
                    carrier_used = self.carrier_override or self.config.get("carrier", "cmcc")
                    if self.login(student_id, password):
                        actions.append({"step": f"使用账号 {student_id} 登录校园网认证", "result": "success"})
                        self._remember_auth_info(student_id, carrier_used)
                        time.sleep(2)
                        auth_ok = self.ping_host(cfg["public_test_host"])
                        if auth_ok:
                            check_auth.update(status="ok", problem="", fix="",
                                              detail="认证成功，可正常访问外网")
                        else:
                            actions.append({"step": "验证外网连通性", "result": "fail",
                                            "detail": "认证后仍无法访问外网"})
                            check_auth.update(status="fail",
                                              problem="认证后仍无法访问外网",
                                              fix="请确认账号是否欠费/在线设备超限，或联系网络管理员")
                    else:
                        actions.append({"step": "登录校园网认证", "result": "fail",
                                        "detail": "登录请求失败"})
                        check_auth.update(status="fail",
                                          problem="登录认证失败",
                                          fix="请检查学号、密码与运营商线路选择是否正确")
                if not auth_ok:
                    continue

            # —— 第 4 步：域名解析 ——
            self.log("开始检测域名解析服务。")
            self.flush_dns_cache()
            actions.append({"step": "清除 DNS 缓存", "result": "success"})
            if self.ping_host(cfg["test_domain"]):
                check_dns.update(status="ok", problem="", fix="",
                                 detail=f"{cfg['test_domain']} 解析正常")
                fixed = True
                break

            self.log("域名解析失败，正在设置公共 DNS 服务器。")
            self._record_network_original(card)
            self.set_custom_dns(card, cfg["dns_primary"], cfg["dns_secondary"])
            actions.append({"step": f"设置 DNS 为 {cfg['dns_primary']} / {cfg['dns_secondary']}",
                            "result": "success"})
            if self.ping_host(cfg["test_domain"]):
                check_dns.update(status="ok", problem="", fix="",
                                 detail="使用公共 DNS 后解析恢复正常")
                fixed = True
                break

            self.log("公共 DNS 无效，正在切换为校内 DNS 服务器。")
            self.set_custom_dns(card, cfg["campus_dns_primary"], cfg["campus_dns_secondary"])
            actions.append({"step": f"设置 DNS 为校内 {cfg['campus_dns_primary']} / {cfg['campus_dns_secondary']}",
                            "result": "success"})
            if self.ping_host(cfg["test_domain"]):
                check_dns.update(status="ok", problem="", fix="",
                                 detail="使用校内 DNS 后解析恢复正常")
                fixed = True
                break

            self.log("域名解析仍然失败，正在将 DNS 恢复为 DHCP 并再次尝试。")
            self.set_dhcp_and_renew(card)
            actions.append({"step": "将 DNS 恢复为 DHCP 自动获取", "result": "success"})
            if self.ping_host(cfg["test_domain"]):
                check_dns.update(status="ok", problem="", fix="",
                                 detail="恢复 DHCP 后解析恢复正常")
                fixed = True
                break

            actions.append({"step": "尝试修复 DNS 解析", "result": "fail",
                            "detail": "公共 DNS / 校内 DNS / DHCP 均无效"})
            check_dns.update(status="fail",
                             problem=f"无法解析 {cfg['test_domain']}",
                             fix="已尝试多种 DNS 方案均无效，可能为本地网络故障，请联系网络管理员")

        ok = fixed and not any(c["status"] in ("fail", "warn") for c in checks)
        self.log("一键修复完成：" + ("网络一切正常。" if ok else "仍有问题未解决，请查看各项目详情。"))
        return self._report(ok, checks, actions)


# ============================ 命令行入口 ============================

def main():
    if not is_supported_windows():
        print("本程序仅支持 Windows 10 及以上版本的 Windows 系统。")
        input("按回车键退出...")
        return

    # 适用范围说明：本工具只处理宿舍区校园网，公共区域网络给出官方教程指引
    print("说明：本工具仅适用于校园宿舍区网络（WiFi 名称含“DORM”）的检测与修复。")
    print("      教学楼、图书馆等公共区域校园网（JSU-WLAN）使用方法不同，请参照信息中心教程：")
    print("      公共区域入网图文教程: https://nic.jsu.edu.cn/fwzn/wljr/cysz/ee4c8a1479144ac2af2b814e37c316ce.htm")
    print("      新生校园网络使用指南: https://nic.jsu.edu.cn/xwgg/tzgg/227b7dfe9e4741f99e6918b8c37c7a98.htm")
    print()

    # 命令行撤销：python core.py revert
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("revert", "undo", "撤销"):
        fixer = CampusNetworkFixer(config=load_config(), log=print, interaction=None)
        fixer.revert_all_changes()
        input("按回车键退出...")
        return

    fixer = CampusNetworkFixer(
        config=load_config(),
        log=print,
        interaction=CliInteraction(),
    )

    if not CampusNetworkFixer.is_admin():
        fixer.log("警告：当前未以管理员身份运行，netsh 等网络设置操作可能失败。")

    report = fixer.run_fix()
    if report.get("ok"):
        fixer.log("全部检测完成，网络状态正常。")
    else:
        fixer.log("自动修复流程已结束，网络仍未完全恢复，请按上方提示处理。")
    input("按回车键退出...")


if __name__ == "__main__":
    main()
