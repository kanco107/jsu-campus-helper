; 校园网助手 - Inno Setup 安装脚本
#define MyAppName "校园网助手"
#define MyAppVersion "1.2.1"
#define MyAppPublisher "校园网助手"
#define MyAppExeName "校园网助手.exe"
#define MyAppDir "E:\xyw\校园网助手\dist\校园网助手"

[Setup]
AppId={{8B3E2F1A-4C5D-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=E:\xyw\校园网助手\installer
OutputBaseFilename=校园网助手_v{#MyAppVersion}_setup
SetupIconFile=E:\xyw\校园网助手\assets\logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 请求管理员权限（网络修复 + .NET 安装都需要）
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
; 64位安装
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
; —— 运行环境（仅在目标系统“缺失”对应组件时才显示该勾选项；默认勾选）——
Name: "install_dotnet"; Description: "安装 .NET Framework 4.8 运行环境（必需）"; GroupDescription: "运行环境（缺少会导致程序无法运行，建议保持勾选）:"; Check: not IsDotNet48Installed
Name: "install_webview2"; Description: "安装 Edge WebView2 运行环境（必需）"; GroupDescription: "运行环境（缺少会导致程序无法运行，建议保持勾选）:"; Check: not IsWebView2Installed
; —— 附加图标 ——
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "startmenuicon"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加图标:"

[Files]
; 打包整个 dist 目录（包含 exe、依赖 DLL、资源文件）
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; .NET Framework 4.8 离线安装包（仅在“缺失且用户勾选”时释放并安装）
Source: "E:\xyw\校园网助手\redist\ndp48-x86-x64-allos-enu.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: ShouldInstallDotNet
; 注：WebView2 完整离线安装包（约 247MB）已随程序打包在 {app}\_internal\redist\ 中，
; 无需在此单独引用（目标用户可能无网，必须用离线包，不能用在线引导）

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\校园网助手.exe"; Tasks: startmenuicon
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\校园网助手.exe"; Tasks: desktopicon

[Run]
; .NET Framework 4.8：缺失且用户勾选时离线静默安装（/norestart 不强制重启）
Filename: "{tmp}\ndp48-x86-x64-allos-enu.exe"; Parameters: "/q /norestart"; StatusMsg: "正在安装 Microsoft .NET Framework 4.8 运行环境（约 1-3 分钟）..."; Check: ShouldInstallDotNet; Flags: waituntilterminated
; WebView2：缺失且用户勾选时，用随包的完整离线安装包静默安装（无需联网）
Filename: "{app}\_internal\redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 运行环境（约 1 分钟）..."; Check: ShouldInstallWebView2; Flags: waituntilterminated
; 再启动主程序
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
; 卸载时清理 WebView2 缓存（用户配置 config.json 保留在 {localappdata}，不删）
Type: filesandordirs; Name: "{localappdata}\校园网助手\wv2_data"

[Code]
function IsDotNet48Installed: Boolean;
var
  Release: Cardinal;
begin
  { .NET Framework 4.8 的 Release 注册表值 >= 528040 }
  Result := RegQueryDWordValue(HKLM,
    'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
    'Release', Release) and (Release >= 528040);
end;

function IsWebView2Installed: Boolean;
var
  Ver: String;
begin
  { WebView2 Runtime 检测：注册表 Clients 键下 pv 值为版本号。
    依次查 per-machine（32位视图 WOW6432Node）、per-machine（64位视图）、per-user。 }
  Result := RegQueryStringValue(HKLM32,
    'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'pv', Ver) and (Ver <> '');
  if not Result then
    Result := RegQueryStringValue(HKLM64,
      'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
      'pv', Ver) and (Ver <> '');
  if not Result then
    Result := RegQueryStringValue(HKCU,
      'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
      'pv', Ver) and (Ver <> '');
end;

{ 是否需要安装：系统缺失 且 用户在向导中勾选 }
function ShouldInstallDotNet: Boolean;
begin
  Result := (not IsDotNet48Installed) and IsTaskSelected('install_dotnet');
end;

function ShouldInstallWebView2: Boolean;
begin
  Result := (not IsWebView2Installed) and IsTaskSelected('install_webview2');
end;

{ 在“选择附加任务”页点击下一步时：若缺失必需组件却取消了勾选，弹窗警告 }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectTasks then
  begin
    if (not IsDotNet48Installed) and (not IsTaskSelected('install_dotnet')) then
    begin
      if MsgBox(
           '检测到系统未安装 Microsoft .NET Framework 4.8 运行环境。' #13#10 #13#10
           + '不安装该组件，校园网助手将无法启动。' #13#10
           + '建议返回并勾选“安装 .NET Framework 4.8 运行环境”。' #13#10 #13#10
           + '是否仍要取消安装该组件并继续？',
           mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        { 用户坚持取消：继续 }
      else
        Result := False;
    end;
    if Result and (not IsWebView2Installed) and (not IsTaskSelected('install_webview2')) then
    begin
      if MsgBox(
           '检测到系统未安装 Microsoft Edge WebView2 运行环境。' #13#10 #13#10
           + '不安装该组件，校园网助手的界面将无法显示。' #13#10
           + '建议返回并勾选“安装 Edge WebView2 运行环境”。' #13#10 #13#10
           + '是否仍要取消安装该组件并继续？',
           mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        { 用户坚持取消：继续 }
      else
        Result := False;
    end;
  end;
end;
