# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：校园网助手
打包后生成单目录（onedir）形式，包含 exe + 依赖 + 资源文件。
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# 精简版：set CAMPUS_LITE=1 后打包，不内嵌 WebView2 离线安装包（约少 247MB）；
# 安装器由 installer.iss 的 /DLite=1 配套生成（同时不含 .NET 4.8 离线包）
LITE = os.environ.get("CAMPUS_LITE") == "1"

# 完整收集 pywebview 和 pythonnet（含数据文件、二进制、隐藏导入）
datas, binaries, hiddenimports = [], [], []
for pkg in ('webview', 'pythonnet', 'clr_loader'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 项目资源：ui/index.html、标题栏 logo.png、窗口图标 logo.ico（只读）
datas += [
    ('ui/index.html', 'ui'),
    ('ui/logo.png', 'ui'),
    ('assets/logo.ico', 'assets'),
]
# WebView2 完整离线安装包（x64，约 247MB）：仅完整版打包；
# 精简版不内嵌（系统已自带 WebView2 时可直接运行，缺失需自行联网安装）
if not LITE:
    datas += [
        ('redist/MicrosoftEdgeWebView2RuntimeInstallerX64.exe', 'redist'),
    ]

# 额外隐藏导入
hiddenimports += ['clr', 'psutil', 'requests', 'bottle', 'proxy_tools']

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='校园网助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='校园网助手',
)


