; Inno Setup script. Compiled by packaging\build.ps1 after PyInstaller has produced dist\SuiteLocal.
; Per-user install: no administrator rights. User data lives in %LOCALAPPDATA%\SuiteLocal and is
; never touched by the uninstaller.
#define AppName "SuiteLocal"
#define AppVersion "0.1.0"

[Setup]
AppId={{6F3B1C52-8A47-4D0E-9B6A-5C2E7D1F4A93}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SuiteLocal-Setup
SetupIconFile=suitelocal.ico
UninstallDisplayIcon={app}\SuiteLocal.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\SuiteLocal\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\SuiteLocal.exe"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\SuiteLocal.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SuiteLocal.exe"; Description: "Abrir SuiteLocal"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] entry for %LOCALAPPDATA%\SuiteLocal: the database, backups and certificates stay.
