; Inno Setup script - builds BelgeOCR-Setup.exe from dist\BelgeOCR
#define AppVersion GetEnv("BELGEOCR_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1E3A52-8E7B-4C0F-9B7E-2B1F0E4C7A11}
AppName=BelgeOCR
AppVersion={#AppVersion}
AppPublisher=BelgeOCR
DefaultDirName={autopf}\BelgeOCR
DefaultGroupName=BelgeOCR
OutputDir=..\dist
OutputBaseFilename=BelgeOCR-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\BelgeOCR.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\BelgeOCR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BelgeOCR"; Filename: "{app}\BelgeOCR.exe"
Name: "{group}\{cm:UninstallProgram,BelgeOCR}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BelgeOCR"; Filename: "{app}\BelgeOCR.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BelgeOCR.exe"; Description: "{cm:LaunchProgram,BelgeOCR}"; Flags: nowait postinstall skipifsilent
