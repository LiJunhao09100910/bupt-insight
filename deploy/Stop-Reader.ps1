$ErrorActionPreference='Stop'
$Project=Split-Path -Parent $PSScriptRoot
$RecordPath=Join-Path $Project '.local\reader-process.json'
if (-not (Test-Path -LiteralPath $RecordPath)) { exit 0 }
$Record=Get-Content -LiteralPath $RecordPath -Raw | ConvertFrom-Json
$Process=Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
if ($Process) {
    # A PID can be reused. Both image path and start time must match our launcher.
    if ($Process.Path -eq $Record.python -and $Process.StartTime.ToUniversalTime().ToString('o') -eq $Record.start_time) {
        # Windows venv python.exe is a redirector with a child interpreter.
        # Stop only this verified launcher's process tree, not other Python jobs.
        & (Join-Path $env:WINDIR 'System32\taskkill.exe') /PID $Process.Id /T /F | Out-Null
    } else { throw '进程身份不匹配，未停止其他程序。' }
}
Remove-Item -LiteralPath $RecordPath -Force
