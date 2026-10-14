; Super Agents for Windows: one Setup.exe, the way Claude's and Codex's apps install. Per user, no admin: it copies the
; PyInstaller folder to %LOCALAPPDATA%\TeamLoop (connected repos' hooks point there), puts `teamloop` on the user's
; PATH, makes Start-menu and desktop shortcuts, closes a running copy first, opens the app, and leaves an uninstaller
; in Settings > Apps. The app's data (~\.teamloop) stays when it's uninstalled.
; Build, after PyInstaller:  iscc /DVersion=0.3.0 packaging\SuperAgents.iss   (makes dist\SuperAgents-Setup.exe)

#ifndef Version
  #error Pass the app's version: iscc /DVersion=x.y.z packaging\SuperAgents.iss
#endif

[Setup]
AppId={{A16697DB-3F8E-4480-860F-95FE57C36965}
AppName=Super Agents
AppVersion={#Version}
AppVerName=Super Agents {#Version}
AppPublisher=SoloBrain Technologies
AppPublisherURL=https://teamloop.vercel.app
AppSupportURL=https://github.com/JrKrishh/teamloop-team
VersionInfoVersion={#Version}
VersionInfoProductName=Super Agents
DefaultDirName={localappdata}\TeamLoop
PrivilegesRequired=lowest
; one click, like Claude's: no pages to answer, a progress bar, then the app opens
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
WizardStyle=modern
SetupIconFile=..\brand\icon.ico
UninstallDisplayIcon={app}\SuperAgents.exe
UninstallDisplayName=Super Agents
OutputDir=..\dist
OutputBaseFilename=SuperAgents-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no

[InstallDelete]
; a clean copy of the bundle's internals each time, so nothing from an older build lingers
Type: filesandordirs; Name: "{app}\_internal"
; the shortcuts' name before 0.3
Type: files; Name: "{userprograms}\TeamLoop.lnk"
Type: files; Name: "{userdesktop}\TeamLoop.lnk"

[Files]
Source: "..\dist\teamloop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Super Agents"; Filename: "{app}\SuperAgents.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "Your team's AI agents, on one page"
Name: "{userdesktop}\Super Agents"; Filename: "{app}\SuperAgents.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "Your team's AI agents, on one page"

[Run]
Filename: "{app}\SuperAgents.exe"; WorkingDir: "{%USERPROFILE}"; Flags: nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM SuperAgents.exe"; Flags: runhidden; RunOnceId: "CloseTheApp"

[Code]
const
  EnvKey = 'Environment';
  WebView2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2: Boolean;
var
  V: String;
begin
  Result := (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2, 'pv', V) and (V <> '') and (V <> '0.0.0.0'))
    or (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2, 'pv', V) and (V <> '') and (V <> '0.0.0.0'));
end;

function InitializeSetup: Boolean;
begin
  // The window is drawn by Microsoft Edge WebView2, which Windows 11 and an up-to-date Windows 10 already have
  if not HasWebView2 then
    SuppressibleMsgBox('Super Agents draws its window with Microsoft Edge WebView2, which this PC doesn''t have yet.' + #13#10#13#10 +
      'Setup will go on. Before opening Super Agents, get WebView2 free from Microsoft: https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      mbInformation, MB_OK, IDOK);
  Result := True;
end;

function OnPath(Dir: String): Boolean;
var
  Path: String;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Path) then
    Path := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') > 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Path: String;
begin
  // `teamloop` on the user's PATH, once
  if (CurStep = ssPostInstall) and not OnPath(ExpandConstant('{app}')) then
  begin
    if not RegQueryStringValue(HKCU, EnvKey, 'Path', Path) then
      Path := '';
    if (Path <> '') and (Copy(Path, Length(Path), 1) <> ';') then
      Path := Path + ';';
    RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Path + ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Path, Dir: String;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  Dir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Path) then
    exit;
  Path := ';' + Path + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Path));
  if P = 0 then
    exit;
  Delete(Path, P, Length(Dir) + 1);
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Copy(Path, 2, Length(Path) - 2));
end;
