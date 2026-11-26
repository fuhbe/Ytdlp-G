#define AppName "Ytdlp-G"
#define AppVersion "1.4.0-beta.2"
[Setup]
AppId={{D6B67919-F420-4550-B954-474B95E4A72A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ytdlp-G contributors
DefaultDirName={localappdata}\Programs\Ytdlp-G Beta
DefaultGroupName=Ytdlp-G Beta
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
Name: "{autoprograms}\Ytdlp-G Beta"; Filename: "{app}\Ytdlp-G.exe"
Name: "{autodesktop}\Ytdlp-G Beta"; Filename: "{app}\Ytdlp-G.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
[Run]
Filename: "{app}\Ytdlp-G.exe"; Description: "{cm:LaunchProgram,Ytdlp-G}"; Flags: nowait postinstall skipifsilent
