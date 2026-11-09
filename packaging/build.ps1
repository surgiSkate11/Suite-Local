# Builds dist\SuiteLocal\SuiteLocal.exe and, when Inno Setup is installed, the installer.
# Without Inno Setup it produces dist\SuiteLocal.zip as the fallback deliverable.
# Run from anywhere:  .\packaging\build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host 'Limpiando build y dist...'
foreach ($folder in 'build', 'dist') {
    if (Test-Path $folder) { Remove-Item -Recurse -Force $folder }
}

Write-Host 'Generando icono...'
python packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar el icono.' }

Write-Host 'Ejecutando PyInstaller...'
python -m PyInstaller packaging\suitelocal.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller fallo.' }

$exe = Join-Path $root 'dist\SuiteLocal\SuiteLocal.exe'
if (-not (Test-Path $exe)) { throw "No se genero $exe" }
$size = [math]::Round((Get-ChildItem dist\SuiteLocal -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "OK: $exe ($size MB en dist\SuiteLocal)"

# Inno Setup: PATH first, then the usual install folders (system-wide and per-user).
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ($iscc) {
    Write-Host 'Compilando instalador con Inno Setup...'
    & $iscc packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup fallo.' }
    Write-Host "Instalador: $(Join-Path $root 'dist\SuiteLocal-Setup.exe')"
} else {
    Write-Host 'Inno Setup no esta instalado: se crea un zip como alternativa.'
    $zip = Join-Path $root 'dist\SuiteLocal.zip'
    # Antivirus scans of the fresh files can lock them for a moment: retry a few times.
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Compress-Archive -Path dist\SuiteLocal -DestinationPath $zip -Force
            break
        } catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds 5
        }
    }
    Write-Host "Zip: $zip"
}
