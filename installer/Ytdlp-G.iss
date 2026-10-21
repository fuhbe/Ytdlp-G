#define AppName "Ytdlp-G"
#define AppVersion "1.2.0"
[Setup]
AppId={{916F5287-2406-4128-AE7C-23BB827B38CE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ytdlp-G contributors
DefaultDirName={localappdata}\Programs\Ytdlp-G
DefaultGroupName=Ytdlp-G
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\artifacts
OutputBaseFilename=Ytdlp-G-Setup
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\Ytdlp-G.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Files]
Source: "..\dist\Ytdlp-G\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.flag,data\*"
[Icons]
Name: "{autoprograms}\Ytdlp-G"; Filename: "{app}\Ytdlp-G.exe"
Name: "{autodesktop}\Ytdlp-G"; Filename: "{app}\Ytdlp-G.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
[Run]
Filename: "{app}\Ytdlp-G.exe"; Description: "{cm:LaunchProgram,Ytdlp-G}"; Flags: nowait postinstall skipifsilent
