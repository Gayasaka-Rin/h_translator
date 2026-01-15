Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\h_translator_service.py""", 0, False
