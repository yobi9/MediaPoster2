; MediaArt Auto-Sync - Inno Setup 6 installer (Next -> Next -> Finish)
;
; Build with:  ISCC.exe installer\mediaart.iss
; or with:    installer\build_installer.bat
;
; The version is NOT hard-coded here: build_installer.bat reads it from
; app\config.py (VERSION) and passes it with /DAppVersion=..., together with
; the file names derived from it. The values below are only fallbacks.
;
; The default icon is used on purpose: the repository has no .ico file yet.
; Adding SetupIconFile=... later is a one-line change.

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#ifndef AppExe
  #define AppExe "MediaArtAutoSync-v1.0.1.exe"
#endif
#ifndef OutputBase
  #define OutputBase "MediaArtAutoSync-Setup-1.0.1"
#endif

[Setup]
AppId={{43E82B57-3A70-4291-9BCA-3C2D788EE6D2}
AppName=MediaArt Auto-Sync
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\MediaArt Auto-Sync
DefaultGroupName=MediaArt Auto-Sync
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=Output
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\icon.ico

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MediaArt Auto-Sync"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\Uninstall MediaArt Auto-Sync"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\MediaArt Auto-Sync"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,MediaArt Auto-Sync}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
