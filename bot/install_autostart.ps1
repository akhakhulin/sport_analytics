# Register Telegram bot in Windows Task Scheduler.
#
# Run (PowerShell as regular user, from project root):
#   cd C:\1с_dev\garmin_analytics
#   PowerShell -ExecutionPolicy Bypass -File bot\install_autostart.ps1
#
# What it does:
#   - Creates scheduled task "GarminBot" in user's Task Scheduler
#   - Trigger: At log on
#   - Action: pythonw.exe -m bot.main  (no console window)
#   - Settings: Restart 5x with 1 min interval on failure
#   - No admin rights required
#   - No .vbs/.bat wrappers - works with any project path

$TaskName = "GarminBot"
$ProjectRoot = (Get-Location).Path

# Find pythonw.exe - prefer venv, fallback to system
$VenvPythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (Test-Path $VenvPythonW) {
    $PythonW = $VenvPythonW
    Write-Host "Using venv pythonw.exe: $PythonW"
} else {
    try {
        $SysPython = (Get-Command python -ErrorAction Stop).Source
        $SysPythonW = $SysPython -replace "python\.exe$","pythonw.exe"
        if (Test-Path $SysPythonW) {
            $PythonW = $SysPythonW
            Write-Host "Using system pythonw.exe: $PythonW"
        } else {
            Write-Error "pythonw.exe not found. Install Python with GUI option or activate venv."
            exit 1
        }
    } catch {
        Write-Error "python not found in PATH. Activate venv or install Python."
        exit 1
    }
}

# Remove old task + .vbs from previous attempts
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task $TaskName..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
$OldVbs = Join-Path $ProjectRoot "bot\start_bot_silent.vbs"
if (Test-Path $OldVbs) {
    Remove-Item $OldVbs -Force
    Write-Host "Removed legacy wrapper $OldVbs"
}

# Trigger: at user logon
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Action: pythonw.exe -m bot.main, working dir = project root
$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "-m bot.main" `
    -WorkingDirectory $ProjectRoot

# Settings: restart on failure + IgnoreNew = если экземпляр уже работает,
# второй параллельный не запускать (защита от дублей которая ломает Telegram polling)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew

# Principal: current user
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $Trigger `
    -Action $Action `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Telegram bot for Garmin training analytics" | Out-Null

Write-Host ""
Write-Host "Task '$TaskName' registered" -ForegroundColor Green
Write-Host "  Execute: $PythonW"
Write-Host "  Args:    -m bot.main"
Write-Host "  WorkDir: $ProjectRoot"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  Start now:       Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Stop:            Stop-ScheduledTask -TaskName $TaskName"
Write-Host "  GUI viewer:      taskschd.msc"
Write-Host "  Uninstall:       bot\uninstall_autostart.ps1"
