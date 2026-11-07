param([int]$Puerto = 18743)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
    'python',
    'py'
)
$basePython = $null
foreach ($candidate in $pythonCandidates) {
    try {
        $resolved = & $candidate -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) { $basePython = $resolved.Trim(); break }
    } catch { continue }
}
if (-not $basePython) { throw 'Instala Python 3.12 o posterior para iniciar Entrelíneas.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $basePython -m venv .venv
    # Algunos entornos integrados no incluyen ensurepip; el instalador base sirve de alternativa.
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'No se ha podido crear el entorno Python.' }
}
& $basePython -m pip --python '.venv\Scripts\python.exe' install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'No se han podido instalar las dependencias.' }
& '.\.venv\Scripts\python.exe' manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'No se ha podido preparar la base de datos.' }
& '.\.venv\Scripts\python.exe' manage.py createcachetable
if ($LASTEXITCODE -ne 0) { throw 'No se ha podido preparar la caché de acceso.' }
$appDebug = & '.\.venv\Scripts\python.exe' -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "entrelineas.settings"); from django.conf import settings; print(settings.DEBUG)'
if ($LASTEXITCODE -ne 0) { throw 'No se ha podido cargar la configuración de la aplicación.' }
if ($appDebug.Trim() -eq 'False') {
    & (Join-Path $PSScriptRoot 'iniciar-publicado.ps1') -Puerto $Puerto
    exit $LASTEXITCODE
}
Write-Host "`nEntrelíneas: http://127.0.0.1:$Puerto" -ForegroundColor Magenta
Write-Host 'En desarrollo, los correos de verificación aparecen en esta terminal. Ctrl+C para cerrar.'
& '.\.venv\Scripts\python.exe' manage.py runserver "127.0.0.1:$Puerto"

