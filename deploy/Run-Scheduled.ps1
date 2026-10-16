param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$LogDirectory = Join-Path $Project ".local\logs"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LogFile = Join-Path $LogDirectory "scheduler.log"
$Utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
Set-Location -LiteralPath $Project
[System.IO.File]::AppendAllText($LogFile, "`nSTART $([DateTimeOffset]::Now.ToString('o'))`n", $Utf8)
try {
    & $PythonPath -X utf8 (Join-Path $Project "run.py") scan --push 2>&1 |
        ForEach-Object { [System.IO.File]::AppendAllText($LogFile, "$_`n", $Utf8) }
    $ResultCode = $LASTEXITCODE
    if ($null -eq $ResultCode) { $ResultCode = 1 }
    & $PythonPath -X utf8 (Join-Path $Project "run.py") status 2>&1 |
        ForEach-Object { [System.IO.File]::AppendAllText($LogFile, "$_`n", $Utf8) }
    [System.IO.File]::AppendAllText($LogFile, "EXIT $ResultCode`n", $Utf8)
    exit $ResultCode
} catch {
    [System.IO.File]::AppendAllText($LogFile, "FAIL scheduled launcher; original exception not logged`n", $Utf8)
    exit 1
}
