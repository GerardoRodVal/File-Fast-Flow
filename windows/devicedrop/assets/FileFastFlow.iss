; Offline installer compiled from the current FileFastFlow application folder.
#ifndef AppSource
  #error AppSource is required
#endif
#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif

[Setup]
AppId={{5DA018EA-912B-4F6C-9246-0D50EA7FD492}
AppName=FileFastFlow
AppVersion={#AppVersion}
AppPublisher=FileFastFlow
AppPublisherURL=https://github.com/GerardoRodVal/File-Fast-Flow
AppUpdatesURL=https://github.com/GerardoRodVal/File-Fast-Flow/releases/latest
DefaultDirName={localappdata}\Programs\FileFastFlow
DefaultGroupName=FileFastFlow
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes
OutputBaseFilename=FileFastFlow-{#AppVersion}-Setup
UninstallDisplayIcon={app}\FileFastFlow.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "{#AppSource}\FileFastFlow.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSource}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FileFastFlow"; Filename: "{app}\FileFastFlow.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\FileFastFlow"; Filename: "{app}\FileFastFlow.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FileFastFlow.exe"; Description: "Abrir FileFastFlow"; Flags: nowait postinstall skipifsilent
