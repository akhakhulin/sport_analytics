' Невидимый запуск Streamlit-дашборда.
' wscript.exe не создаёт окон. Запускает cmd → python → лог в data/dashboard.log.
' Параметр 0 у Run = hidden, False = не ждать завершения (отвязаться).

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir

If Not fso.FolderExists(scriptDir & "\data") Then
    fso.CreateFolder(scriptDir & "\data")
End If

cmd = "cmd /c """".venv\Scripts\python.exe"" -m streamlit run dashboard.py " & _
      "--server.headless=true --browser.gatherUsageStats=false " & _
      "--server.fileWatcherType=none --server.port=8501 " & _
      "> data\dashboard.log 2>&1"""

sh.Run cmd, 0, False
