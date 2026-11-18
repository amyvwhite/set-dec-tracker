import os, winshell
from win32com.client import Dispatch

desktop = winshell.desktop()
path = os.path.join(desktop, "Input Receipts.lnk")
target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Input")

shell = Dispatch('WScript.Shell')
shortcut = shell.CreateShortCut(path)
shortcut.Targetpath = target
shortcut.save()
