# Remove bot registration from Windows Task Scheduler.
#
# Run:
#   PowerShell -ExecutionPolicy Bypass -File bot\uninstall_autostart.ps1

$TaskName = "GarminBot"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed" -ForegroundColor Green
} else {
    Write-Host "Task '$TaskName' is not registered" -ForegroundColor Yellow
}

# Remove legacy vbs wrapper if exists
$VbsPath = Join-Path (Get-Location).Path "bot\start_bot_silent.vbs"
if (Test-Path $VbsPath) {
    Remove-Item $VbsPath -Force
    Write-Host "Removed legacy wrapper $VbsPath"
}

Write-Host ""
Write-Host "Bot will no longer auto-start at Windows logon."
Write-Host "Manual start: bot\start_bot.bat"
