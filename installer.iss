; Installateur DestriPDF — pour tous les utilisateurs du poste, dans Program Files
; (droits d'administrateur). /CURRENTUSER installe pour le seul utilisateur, sans
; droits, dans %LOCALAPPDATA%\Programs (essais automatisés).
; Compilation : "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
; Prérequis : dist\DestriPDF construit par PyInstaller (DestriPDF.spec).

#define AppName "DestriPDF"
#define AppVersion "1.1.0"
#define AppPublisher "Menuiserie Destribois"
#define AppExe "DestriPDF.exe"
#define ProgId "DestriPDF.Document"

[Setup]
AppId={{6C1F0E2A-4B7D-4E1C-9C55-2F8A9B3D5E71}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=installer_output
OutputBaseFilename=DestriPDF-{#AppVersion}-installation
SetupIconFile=assets\destripdf.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
MinVersion=10.0.17763

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "pdfopenwith"; Description: "Proposer DestriPDF pour ouvrir les fichiers PDF (menu « Ouvrir avec » et applications par défaut de Windows)"; GroupDescription: "Fichiers PDF :"
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "dist\DestriPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Lire, modifier, annoter et signer des PDF"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; HKA : HKLM pour une installation pour tous, HKCU avec /CURRENTUSER.
; Type de document propre à DestriPDF
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "Document PDF"; Flags: uninsdeletekey; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: pdfopenwith
; « Ouvrir avec » : l'association par défaut reste le choix de l'utilisateur
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: pdfopenwith
; Déclaration auprès des « Applications par défaut » de Windows
Root: HKA; Subkey: "Software\{#AppName}"; Flags: uninsdeletekeyifempty; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\{#AppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\{#AppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Lire, modifier, annoter et signer des PDF"; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\{#AppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#ProgId}"; Tasks: pdfopenwith
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\{#AppName}\Capabilities"; Flags: uninsdeletevalue; Tasks: pdfopenwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer DestriPDF"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    MsgBox('Le moteur Microsoft Edge WebView2 est introuvable sur ce poste. ' +
      'DestriPDF en a besoin pour afficher son interface. Installez « Microsoft Edge WebView2 Runtime » ' +
      'depuis le site de Microsoft, puis lancez DestriPDF.', mbInformation, MB_OK);
end;
