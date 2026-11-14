; Inno Setup script: guided installer for Stentor on Windows.
;   iscc /DAppVersion=0.4.0 /DSourceDir=..\..\build\dist\Stentor /DOutputDir=..\..\build packaging\windows\stentor.iss
; Installs per user by default (no administrator rights needed); "Install for all users" is offered.
; Reinstalling a newer version upgrades in place; settings and the downloaded voice model are kept.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\dist\Stentor"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\build"
#endif

[Setup]
AppId={{6E5C1B0A-9B7D-4C2E-8F3A-5D1E7A2C9B44}
AppName=Stentor
AppVersion={#AppVersion}
AppVerName=Stentor {#AppVersion}
AppPublisher=Paolo Sani
AppPublisherURL=https://github.com/PaoloSani/stentor
AppSupportURL=https://github.com/PaoloSani/stentor/issues
AppUpdatesURL=https://github.com/PaoloSani/stentor/releases/latest
DefaultDirName={autopf}\Stentor
DefaultGroupName=Stentor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\..\..\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=Stentor-{#AppVersion}-Windows-Setup
SetupIconFile=stentor.ico
UninstallDisplayIcon={app}\Stentor.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a clean upgrade: drop the previous version's bundled libraries
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Stentor"; Filename: "{app}\Stentor.exe"; Comment: "Voice restoration with Sidon"
Name: "{autodesktop}\Stentor"; Filename: "{app}\Stentor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Stentor.exe"; Description: "{cm:LaunchProgram,Stentor}"; Flags: nowait postinstall skipifsilent
