$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction Stop).Source }
Write-Host 'Open http://127.0.0.1:8765 in your browser. Ctrl+C stops the server.'
& $python app.py
