' Невидимый запуск sync.exe — без всплывающего консольного окна.
' Используется планировщиком Task Scheduler для ежедневного автозапуска.
' Логи пишутся в data\sync.log рядом с exe.
'
' При первом запуске Garmin может попросить 2FA-код — но в скрытом режиме
' прочитать его некому. Поэтому первый запуск делайте вручную, двойным
' кликом по sync.exe; после успешного логина токены сохранятся в .garminconnect/
' и дальше скрытый автозапуск будет работать без участия пользователя.

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir

If Not fso.FolderExists(scriptDir & "\data") Then
    fso.CreateFolder(scriptDir & "\data")
End If

cmd = "cmd /c """ & scriptDir & "\sync.exe"" >> ""data\sync.log"" 2>&1"

' 0 = окно скрыто; False = не ждать завершения
sh.Run cmd, 0, False
