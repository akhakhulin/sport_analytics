# Fix: kill duplicate bot instances + apply MultipleInstances=IgnoreNew to existing task

Write-Host "=== Step 1: Stop task + kill all pythonw processes ==="
Stop-ScheduledTask -TaskName GarminBot -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter 'name="pythonw.exe"' | ForEach-Object {
    Write-Host ("Killing PID " + $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== Step 2: Apply IgnoreNew to existing task ==="
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew
Set-ScheduledTask -TaskName GarminBot -Settings $Settings | Out-Null
Write-Host "Settings updated: MultipleInstances=IgnoreNew"

# Clean lock
$LockFile = "C:\1с_dev\garmin_analytics\logs\bot.lock"
if (Test-Path $LockFile) {
    Remove-Item $LockFile -Force
    Write-Host "Lock removed"
}

Write-Host ""
Write-Host "=== Step 3: Start task fresh ==="
Start-ScheduledTask -TaskName GarminBot
Start-Sleep -Seconds 15

Write-Host ""
Write-Host "=== Result ==="
$procs = @(Get-CimInstance Win32_Process -Filter 'name="pythonw.exe"')
Write-Host ("pythonw processes: " + $procs.Count)
$procs | Select ProcessId,CommandLine | Format-List
$info = Get-ScheduledTask -TaskName GarminBot | Get-ScheduledTaskInfo
Write-Host ("Task LastRunTime: " + $info.LastRunTime + ", LastTaskResult: " + $info.LastTaskResult)
