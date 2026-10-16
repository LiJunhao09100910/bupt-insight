$ErrorActionPreference='Stop'
$Project=Split-Path -Parent $PSScriptRoot
$Desktop=[Environment]::GetFolderPath('Desktop')
$Shell=New-Object -ComObject WScript.Shell
$PowerShell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($Entry in @(@{name='BUPT Insight';script='Start-Reader.ps1'},@{name='关闭 BUPT Insight';script='Stop-Reader.ps1'})) {
    $Shortcut=$Shell.CreateShortcut((Join-Path $Desktop ($Entry.name+'.lnk')))
    $Shortcut.TargetPath=$PowerShell
    $Shortcut.Arguments="-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Project\deploy\$($Entry.script)`""
    $Shortcut.WorkingDirectory=$Project
    $Shortcut.WindowStyle=7
    $Shortcut.Description='BUPT Insight 本地校园信息阅读器'
    $Shortcut.Save()
}
Write-Host '已创建桌面打开和关闭快捷方式。'
