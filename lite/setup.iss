[Setup]
AppId=Ytdlp-G-Lite
AppName=Ytdlp-G Lite
AppVersion=0.1.0 Beta 1
DefaultDirName={localappdata}\Programs\Ytdlp-G-Lite
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=Ytdlp-G-Lite-Setup
SetupIconFile=..\assets\icons\app.ico
Compression=lzma2/fast
SolidCompression=yes
UninstallDisplayIcon={app}\Ytdlp-G-Lite.exe
[Files]
Source: "..\build\Ytdlp-G-Lite\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{userprograms}\Ytdlp-G Lite"; Filename: "{app}\Ytdlp-G-Lite.exe"
