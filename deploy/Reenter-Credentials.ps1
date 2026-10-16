param([string]$ResultPath = "")
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project ".venv\Scripts\python.exe"
Set-Location -LiteralPath $Project
Write-Host "BUPT Insight：重新保存学校统一认证凭据" -ForegroundColor Cyan
Write-Host "学号和密码输入均不可见。只在此本地窗口输入，不要发送到聊天。"
& $Python -X utf8 (Join-Path $Project "run.py") credentials save
$ResultCode = $LASTEXITCODE
if ($ResultPath) {
    @{ exit_code = $ResultCode } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
}
if ($ResultCode -eq 0) {
    Write-Host "凭据已安全保存，可以关闭窗口；助手将继续验证。" -ForegroundColor Green
} else {
    Write-Host "未保存成功，请查看上方提示。" -ForegroundColor Yellow
}
Read-Host "按 Enter 关闭窗口" | Out-Null
exit $ResultCode
