param([int]$Port=8765,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$Project=Split-Path -Parent $PSScriptRoot
$Python=Join-Path $Project '.venv\Scripts\python.exe'
$LocalDirectory=Join-Path $Project '.local'
$LogDirectory=Join-Path $LocalDirectory 'logs'
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$Address="http://127.0.0.1:$Port"
try {
    if (-not (Test-Path -LiteralPath $Python)) { throw '请先按照README安装本地Python环境。' }
    $Existing=$null
    try { $Existing=Invoke-RestMethod "$Address/api/identity" -TimeoutSec 2 } catch { }
    if ($Existing -and $Existing.app -eq 'BUPTInsightReader') { if (-not $NoBrowser) { Start-Process $Address }; exit 0 }
    $Arguments="-X utf8 `"$Project\run.py`" web --port $Port"
    $Process=Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDirectory 'reader.log') -RedirectStandardError (Join-Path $LogDirectory 'reader-error.log')
    $Record=@{pid=$Process.Id;port=$Port;start_time=$Process.StartTime.ToUniversalTime().ToString('o');python=$Python}
    $Record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LocalDirectory 'reader-process.json') -Encoding UTF8
    for ($i=0;$i -lt 30;$i++) {
        Start-Sleep -Milliseconds 300
        if ($Process.HasExited) { throw '阅读服务未能启动。请检查端口是否被占用及.local/logs/reader-error.log。' }
        try {
            $Ready=Invoke-RestMethod "$Address/api/identity" -TimeoutSec 1
            if ($Ready.app -eq 'BUPTInsightReader') { if (-not $NoBrowser) { Start-Process $Address }; exit 0 }
        } catch { }
    }
    throw '启动等待超时，请稍后重试。'
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show('BUPT Insight未能打开。请检查本地环境或端口；阅读和采集数据已保留。','BUPT Insight') | Out-Null
    exit 1
}
