# Recette de l'interface dans Microsoft Edge sans fenêtre.
# Échantillons et certificat de test générés à neuf, réglages isolés, aucun accès
# au magasin de certificats de l'utilisateur. Captures dans recette_output\<date>.
param(
    [int]$Port = 8790,
    [string]$Exe = ""  # chemin d'un DestriPDF.exe à recetter ; vide : sources Python
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $root "recette_output\$stamp"
$samples = Join-Path $out 'echantillons'
New-Item -ItemType Directory -Force $samples | Out-Null

& $python -X utf8 (Join-Path $root 'scripts\recette\echantillons.py') $samples | Out-Null

$env:DESTRIPDF_TOKEN = 'recette'
$env:DESTRIPDF_TEST_PFX = Join-Path $samples 'test.pfx'
$env:DESTRIPDF_TEST_PFX_PASSWORD = 'test-destripdf'
$env:DESTRIPDF_SETTINGS_DIR = Join-Path $samples 'reglages'
# Impressions de la recette écrites dans des fichiers, jamais sur une imprimante.
$env:DESTRIPDF_TEST_PRINT_DIR = Join-Path $samples 'impressions'
New-Item -ItemType Directory -Force $env:DESTRIPDF_TEST_PRINT_DIR | Out-Null

$arguments = @('--serve', '--port', "$Port", (Join-Path $samples 'dossier.pdf'))
if ($Exe) {
    $server = Start-Process -FilePath $Exe -ArgumentList $arguments -PassThru
} else {
    $server = Start-Process -FilePath $python -ArgumentList (@('-X', 'utf8', '-m', 'destripdf') + $arguments) -WorkingDirectory $root -PassThru -WindowStyle Hidden
}
Start-Sleep -Seconds 3

$failed = 0
try {
    foreach ($scenario in 'parcours_edition.py', 'parcours_complements.py') {
        Write-Host "== $scenario"
        & $python -X utf8 (Join-Path $root "scripts\recette\$scenario") $out $samples
        if ($LASTEXITCODE -ne 0) { $failed += 1 }
    }
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match '-m destripdf' -and $_.CommandLine -match "--port $Port" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

Write-Host "Captures : $out"
if ($failed) { Write-Host "$failed scénario(s) en échec"; exit 1 }
Write-Host 'Recette réussie'
