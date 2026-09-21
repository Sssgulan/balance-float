' 悬浮窗启动器: 双击启动, 无黑色控制台窗口
' 注意: 不支持多开, 先用右上角关闭按钮退出旧实例
' 依赖 PATH 里的 Python 3; 找不到就把下面 pythonw 改成绝对路径
pythonw = "pythonw.exe"
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
cmd = Chr(34) & pythonw & Chr(34) & " -X utf8 " & Chr(34) & base & "\float_window.py" & Chr(34)
sh.Run cmd, 0, False
