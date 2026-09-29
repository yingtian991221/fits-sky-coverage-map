param([string]$Root = '', [int]$SampleGroups = 0)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction Stop).Source }
if ($Root) { & $python archive.py scan $Root } else { & $python scan_all.py }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($SampleGroups -gt 0) { & $python archive.py sample --groups $SampleGroups --timeout 90 }
& $python archive.py report
