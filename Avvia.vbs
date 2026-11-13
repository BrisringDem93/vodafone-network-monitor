Option Explicit
Dim shell, fso, appPath, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "app.py")
On Error Resume Next
result = shell.Run("pyw -3 """ & appPath & """", 0, False)
If Err.Number <> 0 Then
    MsgBox "Impossibile avviare Python. Installare Python 3 con il Python Launcher per Windows.", 16, "Vodafone Network Monitor"
End If
