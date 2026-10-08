Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = currentDir & "\venv\Scripts\pythonw.exe"
mainPath = currentDir & "\main.py"

If fso.FileExists(pythonwPath) Then
    WshShell.Run """" & pythonwPath & """ """ & mainPath & """", 0, False
Else
    WshShell.Run """" & currentDir & "\venv\Scripts\python.exe"" """ & mainPath & """", 0, False
End If
