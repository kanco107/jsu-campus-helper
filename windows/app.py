# -*- coding: utf-8 -*-
"""校园网助手 —— 桌面图形界面入口（pywebview + FluentUI 风格页面）。

运行前请先安装依赖：
    pip install pywebview psutil requests pythonnet

启动（建议在管理员终端中运行，否则无法修改 IP/DNS）：
    python app.py

说明：
- 界面文件为 ui/index.html（FluentUI 风格，无任何外部网络依赖，离线可用）；
- 前端通过 pywebview.api.* 调用本文件的 Api 类，Python 通过 window.__onEvent 推送事件；
- 核心网络逻辑全部在 core.py 中，本文件只负责桥接：把核心的交互请求
  （选 WiFi、输入账号密码）转为前端弹窗，把用户的选择交回核心。
"""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

# 打包为无控制台 GUI 程序（console=False）后，sys.stdout/stderr 为 None
# （pythonw 行为），此时任何 print() 都会抛 AttributeError（例如配置文件损坏时
# core.load_config 的提示）。启动早期重定向到空设备，保证所有 print 安全。
if getattr(sys, "frozen", False):
    for _stream_name in ("stdout", "stderr"):
        if getattr(sys, _stream_name, None) is None:
            try:
                setattr(sys, _stream_name,
                        open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except Exception:
                pass

# 运行期数据（debug.log、WebView2 缓存、config.json）必须放在用户可写目录：
# 安装到 C:\Program Files 后 exe 同目录只读，故打包版统一用 %LOCALAPPDATA%\校园网助手
def _user_data_dir():
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "校园网助手")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d

# 调试日志（打包后无控制台，写入用户数据目录的 debug.log）
_debug_log_path = os.path.join(_user_data_dir(), "debug.log")

# 日志超过 512KB 时自动重置，避免长期使用无限增长
try:
    if os.path.exists(_debug_log_path) and os.path.getsize(_debug_log_path) > 512 * 1024:
        os.remove(_debug_log_path)
except OSError:
    pass

def _dlog(msg):
    try:
        with open(_debug_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _fatal(msg):
    """致命错误提示：打包后无控制台，用原生消息框弹窗。"""
    _dlog("FATAL: " + msg)
    if getattr(sys, "frozen", False):
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "校园网助手", 0x10)  # MB_ICONERROR
        except Exception:
            pass
    else:
        print(msg)
        input("按回车键退出...")


# ============================ 无边框窗口原生支持 ============================

# 窗口钩子必须长期持有引用：WNDPROC 回调 / 委托一旦被 GC 回收，
# 窗口过程就会指向已释放内存，导致界面随机卡死、"未响应"甚至崩溃
_WINDOW_HOOKS = []


def enable_native_borderless(window):
    """让 pywebview 的无边框窗口保留 Windows 原生体验：阴影、贴边吸附
    （Aero Snap）、边缘拖动缩放、最大化/还原动画。

    原理（与 Chromium/Electron 相同）：pywebview 的 frameless 会把窗口设为
    FormBorderStyle.None，丢失阴影和缩放；这里恢复 WS_CAPTION/WS_THICKFRAME
    等样式，再子类化窗口过程：
    - WM_NCCALCSIZE 把非客户区裁为 0，视觉上无边框但系统行为完整保留；
    - WM_NCHITTEST 把窗口边缘变成缩放热区（客户区铺满后系统不再返回边缘命中）。
    """
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        GWL_STYLE = -16
        GWLP_WNDPROC = -4
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_SYSMENU = 0x00080000
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        WM_NCCALCSIZE = 0x0083
        WM_NCHITTEST = 0x0084
        WM_NCLBUTTONDOWN = 0x00A1
        WM_GETMINMAXINFO = 0x0024
        HTCLIENT = 1
        HTCAPTION = 2
        HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
        HTTOPLEFT, HTTOPRIGHT = 13, 14
        HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
        # 缩放和拖动的 hit-test 值集合
        _RESIZE_HITS = {HTCAPTION, HTLEFT, HTRIGHT, HTTOP,
                        HTTOPLEFT, HTTOPRIGHT, HTBOTTOM,
                        HTBOTTOMLEFT, HTBOTTOMRIGHT}
        SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
        MONITOR_DEFAULTTONEAREST = 0x00000002

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                        ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class MINMAXINFO(ctypes.Structure):
            _fields_ = [("ptReserved", POINT), ("ptMaxSize", POINT),
                        ("ptMaxPosition", POINT), ("ptMinTrackSize", POINT),
                        ("ptMaxTrackSize", POINT)]

        # LRESULT/WPARAM/LPARAM 在 x64 上都是 64 位；返回类型用 c_long
        # 会截断返回值导致行为异常
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                                     wintypes.WPARAM, wintypes.LPARAM)

        GetWindowLongPtrW = user32.GetWindowLongPtrW
        GetWindowLongPtrW.restype = ctypes.c_longlong
        GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        SetWindowLongPtrW = user32.SetWindowLongPtrW
        SetWindowLongPtrW.restype = ctypes.c_longlong
        SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        CallWindowProcW = user32.CallWindowProcW
        CallWindowProcW.restype = ctypes.c_longlong
        CallWindowProcW.argtypes = [ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                                    wintypes.WPARAM, wintypes.LPARAM]
        MonitorFromWindow = user32.MonitorFromWindow
        MonitorFromWindow.restype = wintypes.HMONITOR
        MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        GetMonitorInfoW = user32.GetMonitorInfoW
        GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
        GetWindowRect = user32.GetWindowRect
        GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        GetSystemMetrics = user32.GetSystemMetrics
        GetSystemMetrics.argtypes = [ctypes.c_int]
        GetSystemMetrics.restype = ctypes.c_int
        IsZoomed = user32.IsZoomed
        IsZoomed.argtypes = [wintypes.HWND]
        IsIconic = user32.IsIconic
        IsIconic.argtypes = [wintypes.HWND]
        DefWindowProcW = user32.DefWindowProcW
        DefWindowProcW.restype = ctypes.c_longlong
        DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                    wintypes.WPARAM, wintypes.LPARAM]

        state = {"old_proc": 0}

        def _hit_test_border(x, y, rect):
            """窗口边缘内返回对应的缩放热区代码；不在边缘返回 0。"""
            dx = GetSystemMetrics(SM_CXSIZEFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER)
            dy = GetSystemMetrics(SM_CYSIZEFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER)
            on_left = x < rect.left + dx
            on_right = x >= rect.right - dx
            on_top = y < rect.top + dy
            on_bottom = y >= rect.bottom - dy
            if on_top and on_left:
                return HTTOPLEFT
            if on_top and on_right:
                return HTTOPRIGHT
            if on_bottom and on_left:
                return HTBOTTOMLEFT
            if on_bottom and on_right:
                return HTBOTTOMRIGHT
            if on_left:
                return HTLEFT
            if on_right:
                return HTRIGHT
            if on_top:
                return HTTOP
            if on_bottom:
                return HTBOTTOM
            return 0

        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_NCCALCSIZE and wparam:
                    return 0  # 客户区占满整个窗口，不绘制标题栏/边框
                if msg == WM_GETMINMAXINFO:
                    # 最大化时不遮挡任务栏；限制最小窗口尺寸
                    monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    if GetMonitorInfoW(monitor, ctypes.byref(mi)):
                        mmi = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
                        mmi.ptMaxPosition.x = mi.rcWork.left - mi.rcMonitor.left
                        mmi.ptMaxPosition.y = mi.rcWork.top - mi.rcMonitor.top
                        mmi.ptMaxSize.x = mi.rcWork.right - mi.rcWork.left
                        mmi.ptMaxSize.y = mi.rcWork.bottom - mi.rcWork.top
                        mmi.ptMinTrackSize.x = 840
                        mmi.ptMinTrackSize.y = 620
                    return 0
                if msg == WM_NCLBUTTONDOWN and wparam in _RESIZE_HITS:
                    # 拖动(HTCAPTION)和边缘缩放(HTLEFT 等)交给 DefWindowProc
                    # 直接处理，跳过 WinForms 窗口过程——后者可能不正确调用
                    # DefWindowProc 导致缩放/拖动循环无法启动
                    return DefWindowProcW(hwnd, msg, wparam, lparam)
                if msg == WM_NCHITTEST:
                    # 客户区铺满窗口后系统对全部区域返回 HTCLIENT，
                    # 这里把窗口边缘换成缩放热区（最大化/最小化时不缩放）
                    result = CallWindowProcW(state["old_proc"], hwnd, msg, wparam, lparam)
                    if result != HTCLIENT or IsZoomed(hwnd) or IsIconic(hwnd):
                        return result
                    rect = RECT()
                    if not GetWindowRect(hwnd, ctypes.byref(rect)):
                        return result
                    # lparam 低/高 16 位分别是屏幕坐标 x/y（需要符号扩展）
                    x = ctypes.c_short(lparam & 0xFFFF).value
                    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    return _hit_test_border(x, y, rect) or result
                return CallWindowProcW(state["old_proc"], hwnd, msg, wparam, lparam)
            except Exception:
                try:
                    return CallWindowProcW(state["old_proc"], hwnd, msg, wparam, lparam)
                except Exception:
                    return 0

        cb = WNDPROC(wnd_proc)  # 引用保存在 _WINDOW_HOOKS，防止 GC 后窗口过程悬空

        def apply():
            form = window.native
            hwnd = form.Handle.ToInt64()
            style = GetWindowLongPtrW(hwnd, GWL_STYLE)
            style |= WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            SetWindowLongPtrW(hwnd, GWL_STYLE, style)
            state["old_proc"] = SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p).value)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
            # 设置窗口图标（任务栏 / Alt-Tab / 标题栏左上角）为应用 LOGO
            try:
                if os.path.exists(ICON_FILE):
                    from System.Drawing import Icon
                    form.Icon = Icon(ICON_FILE)
            except Exception as e:
                _dlog(f"set form icon failed: {e}")

        form = window.native
        action = None
        try:  # 必须在 UI 线程上修改窗口过程，用 WinForms 的 BeginInvoke 封送
            from System import Action
            action = Action(apply)
            form.BeginInvoke(action)
        except Exception:
            apply()
        # 关键：回调、状态和委托必须长期持有，否则 BeginInvoke 执行完毕后
        # 委托被回收 → wnd_proc 被释放 → 窗口过程悬空 → 界面卡死/"未响应"
        _WINDOW_HOOKS.append((cb, state, action))
        _dlog("native borderless enabled")
    except Exception as e:
        _dlog(f"enable_native_borderless failed: {e}")

import core

try:
    import webview  # pywebview
except ImportError:
    webview = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# UI 资源（index.html）为只读，打包后从 _MEIPASS 读取；开发时用脚本目录
if getattr(sys, "frozen", False):
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    RESOURCE_DIR = BASE_DIR
UI_FILE = os.path.join(RESOURCE_DIR, "ui", "index.html")
ICON_FILE = os.path.join(RESOURCE_DIR, "assets", "logo.ico")


class UiInteraction(core.Interaction):
    """把核心逻辑的交互请求转发给前端弹窗，并等待用户答复。

    - pick_wifi()      -> 推送 wifi_request 事件，前端弹 WiFi 选择弹窗，
                          用户答复后调用 Api.submit_wifi_choice()；
    - get_credentials()-> 推送 creds_request 事件，前端弹登录弹窗，
                          用户答复后调用 Api.submit_credentials()。
    """

    def __init__(self, api):
        self.api = api

    def pick_wifi(self, candidates, current_ssid=""):
        event = threading.Event()
        holder = {"choice": None}
        self.api._pending_wifi = (event, holder)
        keyword = ""
        if self.api._fixer is not None:
            keyword = self.api._fixer.config.get("wifi_keyword", "")
        self.api._emit("wifi_request", candidates=candidates,
                       current=current_ssid, keyword=keyword)
        if not event.wait(timeout=120):
            self.api._emit("log", text="等待选择 WiFi 超时，已跳过。")
        self.api._pending_wifi = None
        return holder["choice"]

    def get_credentials(self, last_account="", prefill_carrier="cmcc"):
        event = threading.Event()
        holder = {"creds": None}
        self.api._pending_creds = (event, holder)
        self.api._emit("creds_request", last_account=last_account, carrier=prefill_carrier)
        if not event.wait(timeout=600):
            self.api._emit("log", text="等待输入账号密码超时，已跳过登录。")
        self.api._pending_creds = None
        return holder["creds"]

    def pick_adapter(self, candidates):
        """多网卡同时连接校园网时，让前端弹窗选择保留哪一张。"""
        event = threading.Event()
        holder = {"choice": None}
        self.api._pending_adapter = (event, holder)
        self.api._emit("adapter_request", candidates=candidates)
        if not event.wait(timeout=120):
            self.api._emit("log", text="等待选择网卡超时，已跳过。")
        self.api._pending_adapter = None
        return holder["choice"]


class Api:
    """暴露给前端 JS 的接口（前端通过 pywebview.api.方法名 调用）。"""

    def __init__(self):
        self.window = None
        self._fixer = None
        self._busy = threading.Lock()
        self._pending_creds = None    # (Event, holder) 登录弹窗等待用户答复
        self._pending_wifi = None     # (Event, holder) WiFi 弹窗等待用户答复
        self._pending_adapter = None  # (Event, holder) 网卡选择弹窗等待用户答复
        self._interaction = UiInteraction(self)
        self._portal_running = False

    # ---------- 内部工具 ----------

    def _emit(self, evt_type, **data):
        """向前端推送事件：window.__onEvent({type:..., ...})"""
        if not self.window:
            _dlog(f"_emit skipped (no window): {evt_type}")
            return
        payload = {"type": evt_type}
        payload.update(data)
        try:
            self.window.evaluate_js(
                f"window.__onEvent({json.dumps(payload, ensure_ascii=False)})")
        except Exception as e:
            _dlog(f"_emit failed for {evt_type}: {e}")

    def _make_fixer(self, interactive=False):
        """创建核心 Fixer。interactive=True 时用户交互走前端弹窗。"""
        fixer = core.CampusNetworkFixer(
            config=core.load_config(),
            log=lambda msg: self._emit("log", text=str(msg)),
            interaction=self._interaction if interactive else None,
        )
        self._fixer = fixer
        return fixer

    def _task(self, mode):
        if not self._busy.acquire(blocking=False):
            self._emit("log", text="当前已有任务在运行，请稍候。")
            return
        try:
            self._emit("busy", running=True, task=mode)
            try:
                fixer = self._make_fixer(interactive=(mode == "repair"))
                if mode == "diagnose":
                    report = fixer.diagnose()
                elif mode == "revert":
                    acts = fixer.revert_all_changes()
                    ok = all(a["result"] == "success" for a in acts)
                    report = {"ok": ok, "kind": "revert",
                              "summary": "撤销完成" if acts else "没有需要撤销的更改",
                              "checks": [], "actions": acts}
                else:
                    report = fixer.run_fix()
            except Exception as e:  # 防止线程异常导致界面永久卡在进度条
                _dlog(f"task '{mode}' failed: {e}")
                self._emit("log", text=f"发生内部错误: {e}")
                report = {"ok": False, "summary": f"程序内部错误: {e}",
                          "checks": [], "actions": []}
            self._emit("done", report=report)
        finally:
            self._fixer = None
            self._busy.release()

    # ---------- 前端调用接口 ----------

    def get_initial_state(self):
        """返回初始数据：配置、默认值、运营商表、管理员状态。"""
        _dlog("get_initial_state called")
        return {
            "config": core.load_config(),
            "defaults": dict(core.DEFAULT_CONFIG),
            "carriers": core.CARRIER_NAMES,
            "is_admin": core.CampusNetworkFixer.is_admin(),
        }

    def open_url(self, url):
        """用系统默认浏览器打开帮助网页（首页提示条中的教程链接）。"""
        url = str(url).strip()
        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "message": "仅支持 http/https 链接"}
        webbrowser.open(url)
        return {"ok": True}

    # ---------- 无边框窗口控制 ----------

    def win_minimize(self):
        """最小化窗口。"""
        try:
            self.window.minimize()
        except Exception:
            pass

    def win_close(self):
        """关闭窗口。"""
        try:
            self.window.destroy()
        except Exception:
            pass

    def win_toggle_maximize(self):
        """最大化 / 还原切换。

        状态用原生 IsZoomed 读取；切换用 pywebview 的 maximize()/restore()，
        它们内部已通过 Control.Invoke 封送到 UI 线程（跨线程直接改
        form.WindowState 不安全，可能造成界面卡死）。
        """
        try:
            hwnd = self.window.native.Handle.ToInt64()
            if ctypes.windll.user32.IsZoomed(hwnd):
                self.window.restore()
            else:
                self.window.maximize()
        except Exception as e:
            _dlog(f"toggle maximize failed: {e}")

    def win_start_drag(self):
        """标题栏拖拽：交给系统原生处理（支持贴边吸附 Aero Snap、
        最大化时拖动自动还原）。

        关键：pywebview 的 JS bridge 在后台线程执行，而 ReleaseCapture 和
        SendMessage(WM_NCLBUTTONDOWN) 必须在 UI 线程上执行——否则
        ReleaseCapture 释放的是后台线程的捕获（无效），且跨线程
        SendMessage 期间鼠标仍被 WebView2 捕获，拖动无法启动。
        用 BeginInvoke 异步封送到 UI 线程，避免 Invoke 同步等待死锁。
        """
        self._start_nc_action(2)  # HTCAPTION

    def win_start_resize(self, direction):
        """边缘缩放：direction 1-8 对应 HTLEFT→HTBOTTOMRIGHT。

        与拖动同理：JS bridge 在后台线程，通过 BeginInvoke 封送到 UI 线程
        执行 ReleaseCapture + SendMessage(WM_NCLBUTTONDOWN, HT*)。
        系统的 WM_NCHITTEST 边缘热区在 WebView2 子窗口覆盖全客户区时
        无法自动触发 WM_NCLBUTTONDOWN（鼠标事件被子窗口消费），
        所以在 JS 中检测边缘 mousedown 并主动调用此方法。
        """
        hit_tests = [10, 11, 12, 13, 14, 15, 16, 17]  # HTLEFT..HTBOTTOMRIGHT
        if not (1 <= direction <= 8):
            return
        self._start_nc_action(hit_tests[direction - 1])

    def _start_nc_action(self, hit_test):
        """在 UI 线程上执行 ReleaseCapture + SendMessage(WM_NCLBUTTONDOWN, hit_test)。"""
        try:
            hwnd = self.window.native.Handle.ToInt64()

            def _act():
                u = ctypes.windll.user32
                u.ReleaseCapture()
                u.SendMessageW(hwnd, 0xA1, hit_test, 0)  # WM_NCLBUTTONDOWN

            from System import Action
            self.window.native.BeginInvoke(Action(_act))
        except Exception as e:
            _dlog(f"_start_nc_action(ht={hit_test}) failed: {e}")

    def _emit_window_state(self):
        """向前端推送当前最大化状态（切换标题栏按钮图标）。"""
        try:
            maximized = int(self.window.native.WindowState) == 2
            self._emit("window_state", maximized=maximized)
        except Exception:
            pass

    def _hook_window_resize(self):
        """监听窗口状态变化（最大化/最小化/还原），同步前端标题栏按钮图标。

        注意：WinForms 的 Resize 事件在 UI 线程上触发，而 evaluate_js 会阻塞
        等待 JS 执行结果、且回调被调度回 UI 线程 —— 在 UI 线程上直接调用会
        死锁（界面卡死、"未响应"）。因此这里只读取窗口状态，把真正的推送
        放到后台线程执行；并且仅在状态切换（普通/最小化/最大化）时推送，
        避免拖动缩放时高频触发。
        """
        try:
            from System import EventHandler

            last = {"state": -1}

            def on_resize(sender, args):
                try:
                    st = int(sender.WindowState)  # 0 普通 / 1 最小化 / 2 最大化
                except Exception:
                    return
                if st == last["state"]:
                    return
                last["state"] = st
                threading.Thread(target=self._emit_window_state, daemon=True).start()

            handler = EventHandler(on_resize)
            self.window.native.Resize += handler
            _WINDOW_HOOKS.append(handler)  # 防止回调被 GC 回收
        except Exception as e:
            _dlog(f"hook resize failed: {e}")

    def start_diagnose(self):
        """一键检测（仅检测，不修改系统，不弹任何窗口）。"""
        threading.Thread(target=self._task, args=("diagnose",), daemon=True).start()

    def start_repair(self):
        """一键修复（需要时会弹出 WiFi 选择 / 登录窗口）。"""
        threading.Thread(target=self._task, args=("repair",), daemon=True).start()

    def revert_all(self):
        """撤销本工具做过的所有系统更改（网卡 / IP/DNS / 代理 / 随机 MAC / WiFi 配置）。"""
        threading.Thread(target=self._task, args=("revert",), daemon=True).start()

    def submit_wifi_choice(self, ssid):
        """前端 WiFi 弹窗答复：空串表示跳过。"""
        if self._pending_wifi:
            event, holder = self._pending_wifi
            holder["choice"] = (ssid or "").strip()
            event.set()
            self._pending_wifi = None

    def submit_adapter_choice(self, name):
        """前端网卡选择弹窗答复：空串表示跳过（不改动网卡）。"""
        if self._pending_adapter:
            event, holder = self._pending_adapter
            holder["choice"] = (name or "").strip()
            event.set()
            self._pending_adapter = None

    def submit_credentials(self, student_id, password, carrier):
        """前端登录弹窗提交：账号或密码为空表示用户跳过登录。"""
        if self._pending_creds:
            event, holder = self._pending_creds
            if student_id and password:
                holder["creds"] = (student_id, password, carrier)
            event.set()
            self._pending_creds = None

    # ---------- 认证页面登录（内嵌网页 + 轮询检测） ----------

    def start_portal_login(self):
        """弹出认证页面窗口，由学生手动登录；后台轮询外网连通性，
        登录成功后读取网关状态接口（账号/运营商），并自动继续修复流程。"""
        if not self._busy.locked():
            self._emit("log", text="请先点击“一键修复”，出现登录窗口后再使用此功能。")
            return
        if self._portal_running:
            return
        threading.Thread(target=self._portal_task, daemon=True).start()

    def _portal_task(self):
        self._portal_running = True
        portal = None
        try:
            # 必须复用修复线程创建的同一个 fixer 实例，保证 _pending_creds 的
            # holder 一致；若 _fixer 为 None 说明修复已结束，无需打开认证页。
            fixer = self._fixer
            if fixer is None:
                self._emit("log", text="修复流程已结束，无需打开认证页面。")
                return
            portal_url = fixer.config.get("portal_url") or f"http://{fixer.config['gateway']}/"
            self._emit("log", text=f"正在打开认证页面 {portal_url}，请在页面中完成登录...")
            self._emit("portal_opened", url=portal_url)
            try:
                portal = webview.create_window("校园网认证登录", portal_url,
                                               width=540, height=760)
            except Exception as e:
                self._emit("log", text=f"打开认证页面失败: {e}")
                return

            deadline = time.time() + 300  # 最长等待 5 分钟
            success = False
            while time.time() < deadline:
                if self._window_closed(portal):
                    break
                pending = self._pending_creds
                if pending is not None and pending[0].is_set():
                    break  # 用户改在弹窗中手动输入了账号
                if fixer.ping_host(fixer.config["public_test_host"], timeout=5, quiet=True):
                    info = fixer.check_auth_status()
                    if not info.get("account"):
                        time.sleep(1)
                        info = fixer.check_auth_status()
                    self._emit("log", text="检测到认证已生效。")
                    if info.get("account"):
                        self._emit("log", text=f"读取到认证账号：{info['account']}")
                    self._emit("portal_login_success",
                               account=info.get("account", ""), carrier=info.get("carrier", ""))
                    if pending is not None:
                        event, holder = pending
                        holder["creds"] = {"portal_login": True,
                                           "account": info.get("account", ""),
                                           "carrier": info.get("carrier", "")}
                        event.set()
                        self._pending_creds = None
                    success = True
                    break
                time.sleep(2)

            if not success and time.time() >= deadline:
                self._emit("log", text="等待认证超时（5 分钟），可在弹窗中手动输入账号密码。")
        except Exception as e:
            _dlog(f"portal task failed: {e}")
            self._emit("log", text=f"认证页面流程发生错误: {e}")
        finally:
            self._portal_running = False
            if portal is not None:
                try:
                    portal.destroy()
                except Exception:
                    pass
            self._emit("portal_closed")

    @staticmethod
    def _window_closed(win):
        try:
            return bool(win.events.closed.is_set())
        except Exception:
            return False

    def save_config(self, config_json):
        """保存设置；空值视为恢复该项默认值。

        不在设置表单中的键（如 last_account 记住的学号）会被保留，
        避免保存设置时误清空自动学习到的账号。
        """
        try:
            data = json.loads(config_json)
            if not isinstance(data, dict):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"ok": False, "message": "配置格式错误"}

        # 以当前配置为基底，保留不在表单中的键（如 last_account）
        merged = core.load_config()
        for key in core.DEFAULT_CONFIG:
            if key in data:
                if str(data[key]).strip() != "":
                    merged[key] = str(data[key]).strip()
                else:
                    # 表单中显式留空的项恢复默认值
                    merged[key] = core.DEFAULT_CONFIG[key]
        for key in ("ping_timeout", "login_timeout"):
            try:
                merged[key] = int(merged[key])
            except (TypeError, ValueError):
                merged[key] = core.DEFAULT_CONFIG[key]
        if not str(merged["auth_url"]).lower().startswith(("http://", "https://")):
            return {"ok": False, "message": "认证地址必须以 http:// 或 https:// 开头"}

        core.save_config(merged)
        self._emit("log", text="配置已保存。")
        return {"ok": True, "config": merged}

    def reset_config(self):
        """恢复全部默认配置。"""
        core.save_config(dict(core.DEFAULT_CONFIG))
        self._emit("log", text="已恢复默认配置。")
        return {"ok": True, "config": dict(core.DEFAULT_CONFIG)}

    def run_tool(self, name):
        """高级工具：flush_dns / reset_dhcp / set_public_dns / connect_wifi /
        disable_proxy / reset_winhttp"""
        def _run():
            if not self._busy.acquire(blocking=False):
                self._emit("log", text="当前已有任务在运行，请稍候。")
                return
            try:
                self._emit("busy", running=True, task="tool")
                try:
                    fixer = self._make_fixer(interactive=(name == "connect_wifi"))
                    cfg = fixer.config
                    cards = fixer.get_enabled_physical_netcards_with_ipv4()
                    card = cards[0] if cards else ""
                    if name == "flush_dns":
                        fixer.flush_dns_cache()
                    elif name == "reset_dhcp":
                        if card:
                            # 修改前先记录原始 IP/DNS，保证“撤销所有更改”可还原
                            fixer._record_network_original(card)
                            fixer.set_dhcp_and_renew(card)
                        else:
                            fixer.log("未找到可用网卡。")
                    elif name == "set_public_dns":
                        if card:
                            # 同上：记录原始 DNS 配置，供撤销恢复
                            fixer._record_network_original(card)
                            fixer.set_custom_dns(card, cfg["dns_primary"], cfg["dns_secondary"])
                        else:
                            fixer.log("未找到可用网卡。")
                    elif name == "connect_wifi":
                        if fixer.ensure_wifi():
                            fixer.log("校园 WiFi 已就绪。")
                        else:
                            fixer.log("未能连接校园 WiFi，请手动连接。")
                    elif name == "disable_proxy":
                        if fixer.disable_system_proxy():
                            fixer.log("系统代理已关闭。")
                        else:
                            fixer.log("关闭系统代理失败。")
                    elif name == "reset_winhttp":
                        fixer.reset_winhttp_proxy()
                    else:
                        fixer.log(f"未知工具: {name}")
                except Exception as e:  # 防止线程异常导致界面永久卡在进度条
                    _dlog(f"tool '{name}' failed: {e}")
                    self._emit("log", text=f"执行工具时发生内部错误: {e}")
                self._emit("done", report=None)
            finally:
                self._fixer = None
                self._busy.release()
        threading.Thread(target=_run, daemon=True).start()


def _webview2_installed():
    """检测系统是否已安装 WebView2 Runtime（界面渲染内核）。
    查注册表 EdgeUpdate Clients 的 pv 版本号，覆盖 per-machine/per-user。"""
    try:
        import winreg
    except ImportError:
        return True  # 非 Windows：不适用，交给后续流程
    sub = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    candidates = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]
    for root, flag in candidates:
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | flag) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv:
                    return True
        except OSError:
            continue
    return False


def _find_webview2_offline_installer():
    """查找随程序自带的 WebView2 完整离线安装包（x64）。
    返回路径；找不到或文件过小（误拿在线引导）返回 None。"""
    names = ["MicrosoftEdgeWebView2RuntimeInstallerX64.exe"]
    dirs = [
        os.path.join(RESOURCE_DIR, "redist"),       # 打包后 _internal/redist
        os.path.join(BASE_DIR, "redist"),           # 开发模式
        os.path.dirname(sys.executable),            # exe 同目录（免安装版）
        os.path.join(os.path.dirname(sys.executable), "redist"),
    ]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            try:
                # 硬校验：完整离线包约 247MB；小于 100MB 说明不是离线包（在线引导仅约 2MB）
                if os.path.isfile(p) and os.path.getsize(p) > 100 * 1024 * 1024:
                    return p
            except OSError:
                continue
    return None


def _run_elevated_and_wait(exe, params, timeout=300):
    """以管理员权限（UAC 提权）静默运行安装程序并等待结束。返回是否成功。"""
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    sei.lpVerb = "runas"          # 触发 UAC 提权（已是管理员则直接执行）
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = 0                 # SW_HIDE，/silent 本身也无界面
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False              # 用户拒绝 UAC 或启动失败
    ok = False
    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, timeout * 1000)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
        ok = (code.value == 0)
    return ok


def _ensure_webview2():
    """WebView2 缺失时，用随程序自带的【完整离线安装包】本地静默安装（无需联网）。
    返回 True 表示可继续启动。"""
    if _webview2_installed():
        return True
    installer = _find_webview2_offline_installer()
    if not installer:
        _dlog("WebView2 missing and offline installer not found")
        ctypes.windll.user32.MessageBoxW(
            0,
            "程序界面需要 Microsoft Edge WebView2 运行时，当前系统未安装，\n"
            "且未找到随程序附带的离线安装包。\n\n"
            "请使用完整安装包重新安装本程序（安装过程会自动装好该运行环境）。",
            "校园网助手 - 缺少运行组件", 0x10)
        return False
    MB_YESNO, MB_ICONQUESTION, IDYES = 0x04, 0x20, 6
    msg = ("程序界面需要 Microsoft Edge WebView2 运行时，当前系统未检测到该组件。\n\n"
           "是否立即用程序自带的离线安装包安装？（无需联网，约需 1 分钟，\n"
           "安装过程会弹出系统权限确认，请点击“是”）\n点击“否”将退出程序。")
    if ctypes.windll.user32.MessageBoxW(0, msg, "校园网助手 - 缺少运行组件",
                                        MB_YESNO | MB_ICONQUESTION) != IDYES:
        return False
    _dlog(f"installing WebView2 from offline package: {installer}")
    try:
        ok = _run_elevated_and_wait(installer, "/silent /install")
        _dlog(f"WebView2 offline install success={ok}, now installed={_webview2_installed()}")
        if ok and _webview2_installed():
            return True
        ctypes.windll.user32.MessageBoxW(
            0, "WebView2 安装已完成，请重新启动校园网助手。", "校园网助手", 0x40)
        return False
    except Exception as e:
        _dlog(f"webview2 offline install failed: {e}")
        ctypes.windll.user32.MessageBoxW(
            0, f"离线安装失败：{e}\n请使用完整安装包重新安装本程序。",
            "校园网助手 - 缺少运行组件", 0x10)
        return False


# ============================ 单实例保护 ============================

_instance_mutex = None  # 模块级持有互斥体句柄，进程退出时由系统自动释放


def _activate_existing_window():
    """把已运行的校园网助手窗口唤到前台（最小化则先还原）。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "校园网助手")
        if not hwnd:
            return
        if user32.IsIconic(hwnd):
            user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _acquire_single_instance():
    """确保只有一个程序实例在运行。

    返回 True 表示获得运行权；False 表示已有实例在运行（已将其唤到前台并
    弹窗提示），本实例应立即退出。
    """
    global _instance_mutex
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.HANDLE, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        user32 = ctypes.windll.user32
        mutex = kernel32.CreateMutexW(None, False, "Local\\校园网助手_SingleInstance")
        err = ctypes.get_last_error()
        if mutex:
            if err == 183:  # ERROR_ALREADY_EXISTS：已有实例在运行
                kernel32.CloseHandle(mutex)
                _activate_existing_window()
                try:
                    user32.MessageBoxW(
                        0, "校园网助手已在运行中，请勿重复启动。\n"
                           "（已为您切换到正在运行的窗口）",
                        "校园网助手", 0x40)  # MB_ICONINFORMATION
                except Exception:
                    pass
                return False
            _instance_mutex = mutex  # 保持句柄存活直到进程退出
        elif err == 5:  # ERROR_ACCESS_DENIED：已有实例（如以管理员运行）持锁
            _activate_existing_window()
            return False
        return True
    except Exception as e:
        _dlog(f"single instance check failed: {e}")
        return True  # 检查失败不阻止程序运行


def main():
    _dlog(f"main start, frozen={getattr(sys, 'frozen', False)}")
    if not core.is_supported_windows():
        _fatal("本程序仅支持 Windows 10 及以上版本的 Windows 系统。")
        return
    # 单实例保护：已有实例在运行时激活它并提示，本实例退出
    if not _acquire_single_instance():
        return
    if webview is None:
        _fatal("未检测到 pywebview，请先执行：pip install pywebview")
        return
    if not os.path.exists(UI_FILE):
        _fatal(f"未找到界面文件: {UI_FILE}")
        return
    # 预检 WebView2 运行时（免安装版兜底；安装版已在安装阶段自动装好）
    if not _ensure_webview2():
        return

    _dlog(f"UI_FILE={UI_FILE}, creating window")
    # PyInstaller 打包后 WebView2 需要显式指定用户数据目录（缓存/cookie）。
    # 必须放在用户可写目录：安装到 Program Files 后 exe 同目录只读，会报
    # “Microsoft Edge 无法读取和写入其数据目录”，故使用 %LOCALAPPDATA%。
    if getattr(sys, "frozen", False):
        os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER",
                              os.path.join(_user_data_dir(), "wv2_data"))
        # 强制使用 .NET Framework（含 System.Windows.Forms），否则 pythonnet 可能选 .NET Core 导致缺 WinForms
        os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")
    api = Api()
    window = webview.create_window(
        "校园网助手", UI_FILE,
        js_api=api, width=1000, height=780, min_size=(840, 620),
        frameless=True,   # 无边框：标题栏由前端 HTML 绘制（含最小化/最大化/关闭按钮）
        easy_drag=False,  # 拖拽改用原生 WM_NCLBUTTONDOWN（支持贴边吸附、最大化拖动还原）
    )
    api.window = window
    # 标记 window 为不可序列化，避免 pywebview 递归遍历 window.native(WinForms Form)
    # 时因 AccessibilityObject.Bounds.Empty 无限递归导致 JS 桥接初始化失败
    window._serializable = False

    def _after_shown():
        # 窗口原生控件创建完成后：开启无边框原生体验 + 监听最大化状态
        window.events.shown.wait(15)
        time.sleep(0.1)
        try:
            enable_native_borderless(window)
            api._hook_window_resize()
        except Exception as e:
            _dlog(f"post-shown setup failed: {e}")

    threading.Thread(target=_after_shown, daemon=True).start()

    _dlog("window created, calling webview.start")
    try:
        # Windows 10+ 强制使用 Edge Chromium (WebView2) 内核，界面才可正常渲染
        webview.start(gui="edgechromium")
        _dlog("webview.start returned")
    except Exception as e:
        _fatal(f"启动界面失败: {e}\n请确认系统已安装 Microsoft Edge WebView2 运行时（Win10/11 一般自带）。")


if __name__ == "__main__":
    main()
