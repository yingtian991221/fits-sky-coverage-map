param([string]$Python = '.venv\Scripts\python.exe')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path 'tmp','data' | Out-Null
$env:TEMP=Join-Path $PSScriptRoot 'tmp'
$env:TMP=$env:TEMP
$env:PYINSTALLER_CONFIG_DIR=Join-Path $PSScriptRoot 'tmp\pyinstaller-cache'
$env:PIP_CACHE_DIR=Join-Path $PSScriptRoot 'data\pip-cache'
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name FITSSkyMap --distpath dist --workpath tmp\build --specpath tmp --paths $PSScriptRoot --add-data "$PSScriptRoot\static\index.html;static" --add-data "$PSScriptRoot\static\setup.js;static" desktop.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
Write-Host 'Ready: dist\FITSSkyMap\FITSSkyMap.exe. Distribute the entire FITSSkyMap folder.'
