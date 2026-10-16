param(
    [switch]$Uninstall,
    [string]$PythonPath = "",
    [string]$TimesCsv = "07:30,12:30,19:00"
)
$ErrorActionPreference = "Stop"
$TaskName = "BUPTInsight"
$Project = Split-Path -Parent $PSScriptRoot
if ($Uninstall) {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
        Unregister-ScheduledTask -Confirm:$false
    Write-Host "已移除 BUPTInsight 计划任务"
    exit 0
}
if (-not $PythonPath) { $PythonPath = Join-Path $Project ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "找不到 Python，请先安装项目虚拟环境" }
$Times = $TimesCsv.Split(',')
foreach ($Time in $Times) {
    if ($Time -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$') { throw "时间格式应为 HH:MM" }
}
$Triggers = @($Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
$PowerShellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$Action = New-ScheduledTaskAction -Execute $PowerShellPath `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$Project\deploy\Run-Scheduled.ps1`" -PythonPath `"$PythonPath`"" -WorkingDirectory $Project
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers `
    -Settings $Settings -Principal $Principal -Description "北邮通知采集与微信/桌面提醒" -Force | Out-Null
$Check = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($Check.Triggers.Count -ne $Times.Count) { throw "注册后回查触发器数量不符" }
Write-Host "已注册 BUPTInsight；当前用户登录时每天 $TimesCsv 运行。"
Write-Host "休眠不主动唤醒；关机、未登录、无校园网/VPN时不能正常采集。错过触发时间后尽可能补跑一次。"
