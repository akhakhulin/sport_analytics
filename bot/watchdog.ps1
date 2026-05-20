# GarminBot watchdog: проверяет жив ли бот по mtime лога.
# Запускается из Task Scheduler каждые 5 минут.
# Если log file >10 минут без обновлений → перезапустить GarminBot.

$ErrorActionPreference = "Continue"

# Используем $PSScriptRoot чтобы корректно работать с кириллицей в пути.
# $PSScriptRoot = директория где лежит сам скрипт (bot/), идём на уровень
# выше → logs/.
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$LogFile = Join-Path $ProjectRoot "logs\bot.log"
$WatchdogLog = Join-Path $ProjectRoot "logs\watchdog.log"
$StaleThresholdMinutes = 10
$Now = Get-Date
$NowStr = $Now.ToString("yyyy-MM-dd HH:mm:ss")

function Write-WatchdogLog {
    param([string]$Level, [string]$Message)
    "$NowStr | $Level | $Message" | Out-File -FilePath $WatchdogLog -Append -Encoding utf8
}

function Restart-Bot {
    param([string]$Reason)
    Write-WatchdogLog "RESTART" "Reason: $Reason"

    # Завершить если запущен
    & schtasks /end /tn GarminBot 2>&1 | Out-Null
    Start-Sleep -Seconds 3

    # Запустить
    & schtasks /run /tn GarminBot 2>&1 | Out-Null

    # Подождать и проверить что стартанул
    Start-Sleep -Seconds 15
    $newAge = (Get-Date) - (Get-Item $LogFile).LastWriteTime
    if ($newAge.TotalMinutes -lt 1) {
        Write-WatchdogLog "OK" "Bot restarted successfully, log fresh ($([math]::Round($newAge.TotalSeconds,0))s ago)"
    } else {
        Write-WatchdogLog "WARN" "Bot restart triggered but log still stale ($([math]::Round($newAge.TotalMinutes,1))min)"
    }
}

# Основная логика
if (-not (Test-Path $LogFile)) {
    Write-WatchdogLog "ERROR" "Log file not found: $LogFile"
    Restart-Bot -Reason "Log file missing"
    exit 0
}

$LastWrite = (Get-Item $LogFile).LastWriteTime
$AgeMinutes = ($Now - $LastWrite).TotalMinutes
$AgeRounded = [math]::Round($AgeMinutes, 1)

if ($AgeMinutes -gt $StaleThresholdMinutes) {
    Write-WatchdogLog "STALE" "Log age $AgeRounded min > $StaleThresholdMinutes min threshold"
    Restart-Bot -Reason "Log stale: $AgeRounded min"
} else {
    # Здоровый — пишем в лог только каждый час чтоб не флудить
    if ($Now.Minute -lt 5) {
        Write-WatchdogLog "OK" "Log age $AgeRounded min (healthy)"
    }
}

# Ротация watchdog-лога если >1 МБ
if (Test-Path $WatchdogLog) {
    $size = (Get-Item $WatchdogLog).Length
    if ($size -gt 1048576) {
        $archive = "$WatchdogLog.old"
        if (Test-Path $archive) { Remove-Item $archive -Force }
        Move-Item $WatchdogLog $archive -Force
    }
}
