# Регистрация GarminBotWatchdog в Windows Task Scheduler.
# Запускать с правами администратора (или в обычной сессии — задача создаётся в пользовательском пространстве).

$TaskName = "GarminBotWatchdog"
$ScriptPath = "C:\1с_dev\garmin_analytics\bot\watchdog.ps1"

# Удаляем старую задачу если есть
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Удаляю существующую задачу $TaskName..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: запустить PowerShell скрипт
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Trigger: каждые 5 минут начиная с момента активации задачи
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

# Settings: можно работать когда пользователь не залогинен, не останавливать на батарее
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

# Principal: текущий пользователь, без elevation
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Регистрация
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Проверяет mtime bot.log каждые 5 минут. Если >10 мин — рестарт GarminBot."

Write-Host ""
Write-Host "✅ Задача $TaskName зарегистрирована"
Write-Host ""
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, @{Name='NextRun';Expression={(Get-ScheduledTaskInfo $_).NextRunTime}}
