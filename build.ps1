# Construction de DestriPDF : tests, icône, exécutable (mode dossier), test de fumée
# de l'exécutable figé, installateur Inno Setup.
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'

function Step($label) { Write-Host "`n== $label" -ForegroundColor Cyan }

if (-not $SkipTests) {
    Step 'Tests'
    & $python -m pytest tests -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Tests en échec' }
}

Step 'Icône'
& $python -X utf8 scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icône non générée' }

Step 'Exécutable (PyInstaller)'
& $python -m PyInstaller DestriPDF.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0 -or -not (Test-Path 'dist\DestriPDF\DestriPDF.exe')) { throw 'Exécutable non construit' }

Step "Test de fumée de l'exécutable figé"
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("destripdf-fumee-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work | Out-Null
& $python -X utf8 scripts\recette\echantillons.py $work | Out-Null
$env:DESTRIPDF_TOKEN = 'fumee'
$env:DESTRIPDF_TEST_PFX = Join-Path $work 'test.pfx'
$env:DESTRIPDF_TEST_PFX_PASSWORD = 'test-destripdf'
$env:DESTRIPDF_SETTINGS_DIR = Join-Path $work 'reglages'
$frozen = Start-Process -FilePath 'dist\DestriPDF\DestriPDF.exe' -ArgumentList '--serve', '--port', '8799' -PassThru
try {
    Start-Sleep -Seconds 3
    & $python -X utf8 scripts\smoke.py 'http://127.0.0.1:8799/fumee/' $work
    $smoke = $LASTEXITCODE
} finally {
    Stop-Process -Id $frozen.Id -Force -ErrorAction SilentlyContinue
    Remove-Item Env:DESTRIPDF_TOKEN, Env:DESTRIPDF_TEST_PFX, Env:DESTRIPDF_TEST_PFX_PASSWORD, Env:DESTRIPDF_SETTINGS_DIR -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
if ($smoke -ne 0) { throw 'Test de fumée en échec' }

Step 'Installateur (Inno Setup)'
$iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
if (-not (Test-Path $iscc)) { $iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
& $iscc '/Q' 'installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installateur non compilé' }
Get-ChildItem installer_output | Select-Object Name, @{ n = 'Mo'; e = { [math]::Round($_.Length / 1MB, 1) } } | Format-Table -AutoSize
