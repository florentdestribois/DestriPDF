# Publication d'une version de DestriPDF : chaque release porte son installateur.
#   scripts\release.ps1            contrôles et construction complète, rien n'est publié
#   scripts\release.ps1 -Publish   puis étiquette vX.Y.Z, push et release GitHub avec
#                                  l'installateur joint (et son empreinte SHA-256)
# Aucune release sans installateur : la publication n'a lieu qu'après build.ps1 réussi
# (tests, exécutable, test de fumée de l'exécutable figé, installateur).
param([switch]$Publish)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Find-Tool($name, $candidates) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Path $candidate)) { return $candidate } }
    throw "$name introuvable : installez-le ou ajoutez-le au PATH."
}

$git = Find-Tool 'git' @(
    "$env:ProgramFiles\Git\cmd\git.exe",
    "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe",
    "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
)
$gh = Find-Tool 'gh' @("$env:ProgramFiles\GitHub CLI\gh.exe")

# 1. Une seule version : code, installateur, informations de l'exécutable.
$version = (Select-String -Path 'destripdf\__init__.py' -Pattern '__version__ = "([\d.]+)"').Matches[0].Groups[1].Value
$innoVersion = (Select-String -Path 'installer.iss' -Pattern '#define AppVersion "([\d.]+)"').Matches[0].Groups[1].Value
$fileVersion = (Select-String -Path 'build_version.txt' -Pattern "FileVersion', '([\d.]+)'").Matches[0].Groups[1].Value
if ($version -ne $innoVersion -or $version -ne $fileVersion) {
    throw "Versions différentes : destripdf $version, installer.iss $innoVersion, build_version.txt $fileVersion."
}
$tag = "v$version"

# 2. Arbre propre, branche main, étiquette libre.
if (& $git status --porcelain) { throw 'Modifications non commitées : les commiter avant de publier.' }
$branch = (& $git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'main') { throw "Branche « $branch » : publier depuis main." }
if (& $git tag --list $tag) { throw "L'étiquette $tag existe déjà : changer de version." }

# 3. Construction complète : sans installateur vérifié, pas de release.
Write-Host "`n== Construction de DestriPDF $version" -ForegroundColor Cyan
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'build.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Construction en échec : rien n''est publié.' }
$installer = Join-Path $root "installer_output\DestriPDF-$version-installation.exe"
if (-not (Test-Path $installer)) { throw "Installateur absent : $installer" }
if ((Get-Item $installer).VersionInfo.ProductVersion -notlike "$version*") { throw "L'installateur n'annonce pas la version $version." }
$hash = (Get-FileHash $installer -Algorithm SHA256).Hash
if (& $git status --porcelain) { throw 'La construction a modifié des fichiers suivis : vérifier avant de publier.' }

if (-not $Publish) {
    Write-Host "`nPrêt à publier $tag : $installer`nSHA-256 : $hash`nRien n'est publié (relancer avec -Publish)." -ForegroundColor Green
    exit 0
}

# 4. Publication : étiquette, push, release GitHub avec l'installateur.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
$helper = "credential.helper=!'" + ($gh -replace '\\', '/') + "' auth git-credential"
& $git tag -a $tag -m "DestriPDF $version"
if ($LASTEXITCODE -ne 0) { throw "Étiquette $tag non créée." }
& $git -c credential.helper= -c $helper push origin main $tag
if ($LASTEXITCODE -ne 0) { throw "Push en échec : l'étiquette locale $tag reste à pousser." }

$notes = Join-Path ([System.IO.Path]::GetTempPath()) "destripdf-release-$version.md"
$body = (& $git log -1 --format=%B) -join "`n"
$text = "Installateur Windows : DestriPDF-$version-installation.exe (installation dans C:\Program Files\DestriPDF, autorisation Windows demandée)`n`nSHA-256 : $hash`n`n$body"
[System.IO.File]::WriteAllText($notes, $text, (New-Object System.Text.UTF8Encoding $false))
try {
    & $gh release create $tag $installer --title "DestriPDF $version" --notes-file $notes --verify-tag
    if ($LASTEXITCODE -ne 0) { throw "Release $tag non créée : l'étiquette est poussée, relancer « gh release create »." }
} finally {
    Remove-Item -LiteralPath $notes -ErrorAction SilentlyContinue
}
Write-Host "`nRelease $tag publiée avec son installateur (SHA-256 $hash)." -ForegroundColor Green
