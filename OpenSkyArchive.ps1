param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data'),(Join-Path $PSScriptRoot 'tmp') | Out-Null
$env:TEMP=Join-Path $PSScriptRoot 'tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$url='http://127.0.0.1:8765/'
$healthUrl='http://127.0.0.1:8765/api/health'
$ready=$false
try {
    $answer=Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    $ready=$answer.ready -eq $true
} catch { }
if (-not $ready) {
    $localPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $python=if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
    if (-not $python -or -not (Test-Path -LiteralPath $python)) { throw 'Python unavailable; install Python and requirements.txt first' }
    $app=Join-Path $PSScriptRoot 'app.py'
    $log=Join-Path $PSScriptRoot 'data\server.log'
    $err=Join-Path $PSScriptRoot 'data\server-error.log'
    Start-Process -FilePath $python -ArgumentList ('"' + $app + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err | Out-Null
    for ($i=0;$i -lt 60;$i++) {
        Start-Sleep -Milliseconds 500
        try {
            $answer=Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
            if ($answer.ready -eq $true) { $ready=$true; break }
        } catch { }
    }
}
if (-not $ready) { throw "Server did not start; see $err" }
if (-not $NoBrowser) { Start-Process $url }
Write-Output "Sky archive ready: $url"
