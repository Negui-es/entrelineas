param([int]$Puerto = 18743)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $appPython)) { throw 'Prepara primero el entorno Python con iniciar.ps1.' }
if (-not (Test-Path -LiteralPath '.env')) { throw 'Falta la configuración .env de publicación.' }
& $appPython scripts/compile_translations.py
if ($LASTEXITCODE -ne 0) { throw 'No se han podido preparar las traducciones.' }
& $appPython manage.py check --deploy
if ($LASTEXITCODE -ne 0) { throw 'Revisa la configuración antes de publicar.' }
& $appPython manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'No se ha podido preparar la base de datos.' }
& $appPython manage.py createcachetable
if ($LASTEXITCODE -ne 0) { throw 'No se ha podido preparar la caché.' }
& $appPython manage.py collectstatic --noinput
if ($LASTEXITCODE -ne 0) { throw 'No se han podido preparar los archivos de la web.' }
Write-Host 'Entrelíneas: https://entrelineas.negui.es' -ForegroundColor Magenta
Write-Host "Origen del túnel: http://127.0.0.1:$Puerto. Ctrl+C para cerrar."
& $appPython servidor.py --port $Puerto
if ($LASTEXITCODE -ne 0) { throw 'El servidor se ha detenido con un error.' }
