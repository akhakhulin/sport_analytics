"""Установщик задачи GarminBotWatchdog в Windows Task Scheduler.

Создаёт XML определение задачи в UTF-16 (Task Scheduler требует),
затем регистрирует через schtasks /Create /XML.

Триггер: каждые 5 минут.
Действие: powershell.exe -File bot/watchdog.ps1
"""
from __future__ import annotations

import datetime as dt
import getpass
import os
import socket
import subprocess
import sys
from pathlib import Path


TASK_NAME = "GarminBotWatchdog"


def build_xml(project_root: Path) -> str:
    script_path = project_root / "bot" / "watchdog.ps1"
    user = f"{socket.gethostname()}\\{getpass.getuser()}"
    start_time = dt.datetime.now().replace(microsecond=0).isoformat()

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{start_time}</Date>
    <Author>{user}</Author>
    <Description>Watchdog: проверяет mtime bot.log каждые 5 минут. Если &gt;10 мин — рестарт GarminBot.</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start_time}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT3M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script_path}"</Arguments>
      <WorkingDirectory>{project_root}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    xml_path = project_root / "tmp" / "watchdog_task.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)

    xml_content = build_xml(project_root)
    # Task Scheduler требует UTF-16 with BOM
    xml_path.write_text(xml_content, encoding="utf-16")
    print(f"XML создан: {xml_path}")

    # Удалить старую задачу если есть
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )

    # Зарегистрировать новую
    result = subprocess.run(
        ["schtasks", "/Create", "/XML", str(xml_path), "/TN", TASK_NAME],
        capture_output=True, text=True, encoding="cp866",
    )
    print("schtasks output:")
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr, file=sys.stderr)
        return result.returncode

    # Проверка
    check = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        capture_output=True, text=True, encoding="cp866",
    )
    print("\n=== Проверка ===")
    print(check.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
