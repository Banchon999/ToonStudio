; Toon Studio — Windows installer (Inno Setup 6.1 or newer).
;
; Built by .github/workflows/build-windows-installer.yml, which passes:
;   /DAppVersion=3.4.0            the version in app/version.py
;   /DSourceDir=...\ToonStudio    the ordinary PyInstaller build
;   /DPackUrl=https://...         where the optional OCR pack is downloaded from
;   /DPackSha256=...              its SHA-256 (the download is refused otherwise)
;   /DPackMB=... /DPackInstalledBytes=...   sizes, for the component's label
;
; The installer carries the ordinary build, compressed far harder than the
; release zip. The EasyOCR and PaddleOCR-VL engines need PyTorch, which is
; several times the size of everything else, so they are a component: ticked,
; the installer downloads the pack (scripts/make_ocr_pack.py) and lays it over
; the installed app. Left unticked nothing extra is downloaded, and the
; installer can be run again later to add them.
;
; /PACKFILE=path uses a pack already on disk instead of downloading — for a
; machine without internet, and for the build's own test of this script.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\ToonStudio"
#endif
#ifndef PackUrl
  #define PackUrl ""
#endif
#ifndef PackSha256
  #define PackSha256 ""
#endif
#ifndef PackMB
  #define PackMB "0"
#endif
#ifndef PackInstalledBytes
  #define PackInstalledBytes "0"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
; Never change the AppId: it is how an update finds the installed copy.
AppId={{6B0B0A52-6F6C-4D0B-9B4E-7A2C5D1E3F84}
AppName=Toon Studio
AppVersion={#AppVersion}
AppVerName=Toon Studio {#AppVersion}
AppPublisher=Toon Studio
DefaultDirName={autopf}\ToonStudio
DefaultGroupName=Toon Studio
DisableProgramGroupPage=yes
; Per-user by default: no administrator prompt, and the app can be updated
; without one. "Install for all users" is offered on the first page.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=ToonStudio-Setup-x64
SetupIconFile=..\..\resources\icons\icon.ico
UninstallDisplayIcon={app}\ToonStudio.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "standard"; Description: "Standard  /  มาตรฐาน"
Name: "full"; Description: "With EasyOCR and PaddleOCR-VL  /  พร้อมตัวอ่าน EasyOCR และ PaddleOCR-VL"
Name: "custom"; Description: "Custom  /  เลือกเอง"; Flags: iscustom

[Components]
Name: "main"; Description: "Toon Studio, with the built-in text readers (PaddleOCR, manga-ocr, Pororo; their models download on first use)  /  ตัวแอปและตัวอ่านข้อความในตัว"; Types: standard full custom; Flags: fixed
Name: "torchocr"; Description: "EasyOCR and PaddleOCR-VL readers — downloads about {#PackMB} MB more  /  ตัวอ่าน EasyOCR และ PaddleOCR-VL — ต้องดาวน์โหลดเพิ่มราว {#PackMB} MB"; Types: full; ExtraDiskSpaceRequired: {#PackInstalledBytes}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; The app's files change wholesale between versions, and the OCR pack is laid
; over them outside the installer's own record. Starting from an empty folder
; keeps an update — or a reinstall without the pack — from leaving half of an
; older build behind. User data lives elsewhere and is not touched.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\ocr-pack.txt"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main

[Icons]
Name: "{group}\Toon Studio"; Filename: "{app}\ToonStudio.exe"
Name: "{autodesktop}\Toon Studio"; Filename: "{app}\ToonStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ToonStudio.exe"; Description: "{cm:LaunchProgram,Toon Studio}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The pack's files were not put there by [Files], so the uninstaller would
; leave them.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\ocr-pack.txt"

[Code]
var
  DownloadPage: TDownloadWizardPage;

function LocalPack(): String;
begin
  Result := ExpandConstant('{param:PACKFILE|}');
end;

function WantsPack(): Boolean;
begin
  Result := WizardIsComponentSelected('torchocr');
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(
    'Downloading EasyOCR and PaddleOCR-VL',
    'The two extra text readers are being downloaded. This is the large part; the rest is already here.',
    nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or (not WantsPack()) or (LocalPack() <> '') then
    exit;
  if '{#PackUrl}' = '' then
  begin
    SuppressibleMsgBox('This installer was built without the EasyOCR and PaddleOCR-VL download. ' +
      'Toon Studio will be installed without them.', mbInformation, MB_OK, IDOK);
    exit;
  end;
  DownloadPage.Clear;
  DownloadPage.Add('{#PackUrl}', 'ocr-pack.zip', '{#PackSha256}');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      if DownloadPage.AbortedByUser then
        Log('The OCR pack download was cancelled.')
      else
        SuppressibleMsgBox('The EasyOCR and PaddleOCR-VL download failed:' + #13#10 + #13#10 +
          AddPeriod(GetExceptionMessage) + #13#10 + #13#10 +
          'Go back and untick them to install Toon Studio without them, or try again.',
          mbCriticalError, MB_OK, IDOK);
      Result := False;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Pack, Tar: String;
  ResultCode: Integer;
begin
  if (CurStep <> ssPostInstall) or (not WantsPack()) then
    exit;
  Pack := LocalPack();
  if Pack = '' then
    Pack := ExpandConstant('{tmp}\ocr-pack.zip');
  if not FileExists(Pack) then
  begin
    Log('No OCR pack to install: ' + Pack);
    exit;
  end;
  // tar.exe ships with Windows 10 (1803) and later and reads zip archives.
  Tar := ExpandConstant('{sys}\tar.exe');
  WizardForm.StatusLabel.Caption := 'Installing EasyOCR and PaddleOCR-VL...';
  if Exec(Tar, '-xf "' + Pack + '" -C "' + ExpandConstant('{app}') + '"', '',
          SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    SaveStringToFile(ExpandConstant('{app}\ocr-pack.txt'), '{#AppVersion} {#PackSha256}', False)
  else
    SuppressibleMsgBox('EasyOCR and PaddleOCR-VL could not be unpacked (tar exit code ' +
      IntToStr(ResultCode) + '). Toon Studio is installed and works without them; ' +
      'run this installer again to retry.', mbError, MB_OK, IDOK);
end;
