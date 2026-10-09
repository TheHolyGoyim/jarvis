' install_shortcut.vbs
' Run once to (re)create the JARVIS desktop shortcut.
' The shortcut launches jarvis_app.py with pythonw (no console window) —
' the ONE canonical launcher: it boots Ollama + the server and opens the
' web app window. There is no other frontend.

Option Explicit

Dim WshShell, FSO, ScriptDir, AppPy, DesktopPath, Shortcut, PyW

Set WshShell = WScript.CreateObject("WScript.Shell")
Set FSO      = WScript.CreateObject("Scripting.FileSystemObject")

ScriptDir   = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
AppPy       = ScriptDir & "jarvis_app.py"
DesktopPath = WshShell.SpecialFolders("Desktop")

If Not FSO.FileExists(AppPy) Then
    WScript.Echo "ERROR: jarvis_app.py not found in " & ScriptDir
    WScript.Quit 1
End If

' Find pythonw.exe: prefer the PATH'd install, fall back to bare name
PyW = WshShell.ExpandEnvironmentStrings("%LocalAppData%") & "\Python\bin\pythonw.exe"
If Not FSO.FileExists(PyW) Then PyW = "pythonw.exe"

Set Shortcut              = WshShell.CreateShortcut(DesktopPath & "\JARVIS.lnk")
Shortcut.TargetPath       = PyW
Shortcut.Arguments        = """" & AppPy & """"
Shortcut.WorkingDirectory = Left(ScriptDir, Len(ScriptDir) - 1)
Shortcut.Description      = "Launch JARVIS AI Butler"
Shortcut.IconLocation     = "imageres.dll,199"
Shortcut.WindowStyle      = 1
Shortcut.Save

Set Shortcut = Nothing
Set FSO      = Nothing
Set WshShell = Nothing

WScript.Echo "JARVIS shortcut installed on your Desktop!" & Chr(13) & Chr(10) & _
             "Double-click the JARVIS icon anytime to start."
