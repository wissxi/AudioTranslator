; Inno Setup script — builds AudioTranslator-<version>-setup.exe from dist\AudioTranslator
; iscc /DAppVersion=2.0.0 packaging\installer.iss

#define AppName "AudioTranslator"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppId={{8C9B3A4E-5E1F-4B8B-9E2A-6D3F1A7C2B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=wissxi
AppPublisherURL=https://github.com/wissxi/AudioTranslator
AppSupportURL=https://github.com/wissxi/AudioTranslator/issues
AppUpdatesURL=https://github.com/wissxi/AudioTranslator/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=AudioTranslator-{#AppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AudioTranslator.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\AudioTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\AudioTranslator.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\AudioTranslator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AudioTranslator.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
