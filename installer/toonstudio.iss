; Toon Studio's Windows installer (Inno Setup 6).
;
; Built by .github/workflows/build-windows.yml from the PyInstaller folder
; dist\ToonStudio, after that folder has passed its self-tests, and published
; by release.yml as ToonStudio-Windows-x86_64-Setup.exe beside the zip.
;
;   iscc /DAppVersion=3.4.0 installer\toonstudio.iss
;
; It installs for the current user by default (%LOCALAPPDATA%\Programs, no
; administrator prompt), so the in-app updater can run the next one without
; UAC; "Install for all users" is offered in the dialog. User data — settings,
; glossaries, models, projects — lives in the user's data folders, never in
; {app}, so upgrading or uninstalling never touches it.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: it is how an upgrade finds the installation it replaces.
AppId={{6B0E4C7A-3F2D-4B8E-9C51-7A2E8D4F1C93}
AppName=Toon Studio
AppVersion={#AppVersion}
AppVerName=Toon Studio {#AppVersion}
AppPublisher=Toon Studio
AppPublisherURL=https://github.com/Banchon999/ToonStudio
AppSupportURL=https://github.com/Banchon999/ToonStudio/issues
AppUpdatesURL=https://github.com/Banchon999/ToonStudio/releases
VersionInfoVersion={#AppVersion}
SourceDir=..
OutputDir=dist
OutputBaseFilename=ToonStudio-Windows-x86_64-Setup
SetupIconFile=resources\icons\icon.ico
UninstallDisplayIcon={app}\ToonStudio.exe
UninstallDisplayName=Toon Studio
DefaultDirName={autopf}\Toon Studio
DefaultGroupName=Toon Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The updater runs this while the app is open: close it (Restart Manager)
; rather than fail on files in use.
CloseApplications=force
RestartApplications=no
ChangesAssociations=yes
LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "ctpr"; Description: "Open Toon Studio projects (.ctpr) with Toon Studio"; GroupDescription: "File types:"

[InstallDelete]
; A new version's bundle replaces the old one whole: PyInstaller's _internal
; folder changes between versions, and a library left from the previous one
; can be loaded instead of the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\ToonStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Toon Studio"; Filename: "{app}\ToonStudio.exe"
Name: "{group}\{cm:UninstallProgram,Toon Studio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Toon Studio"; Filename: "{app}\ToonStudio.exe"; Tasks: desktopicon

[Registry]
; HKA is HKCU for a per-user install and HKLM for an all-users one.
Root: HKA; Subkey: "Software\Classes\.ctpr\OpenWithProgids"; ValueType: string; ValueName: "ToonStudio.Project"; ValueData: ""; Flags: uninsdeletevalue; Tasks: ctpr
Root: HKA; Subkey: "Software\Classes\ToonStudio.Project"; ValueType: string; ValueName: ""; ValueData: "Toon Studio Project"; Flags: uninsdeletekey; Tasks: ctpr
Root: HKA; Subkey: "Software\Classes\ToonStudio.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\_internal\resources\icons\file_icon.ico"; Tasks: ctpr
Root: HKA; Subkey: "Software\Classes\ToonStudio.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ToonStudio.exe"" ""%1"""; Tasks: ctpr

[Run]
Filename: "{app}\ToonStudio.exe"; Description: "{cm:LaunchProgram,Toon Studio}"; Flags: nowait postinstall skipifsilent
