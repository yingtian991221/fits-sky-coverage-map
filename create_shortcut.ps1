$ErrorActionPreference='Stop'
$desktop=[Environment]::GetFolderPath('Desktop')
$link=Join-Path $desktop 'FITS Sky Coverage Map.lnk'
if (Test-Path -LiteralPath $link) { Write-Output $link; return }
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut($link)
$shortcut.TargetPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'OpenSkyArchive.ps1') + '"'
$shortcut.WorkingDirectory=$PSScriptRoot
$shortcut.Description='Open local FITS sky archive'
$shortcut.IconLocation='C:\Windows\System32\shell32.dll,13'
$shortcut.Save()
Write-Output $link
