import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow

if __name__ == "__main__":
    try:
        # Use a Windows Mutex to ensure only one instance ever runs
        mutex_name = "SetDecTrackerMutex_v1"
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if ctypes.windll.kernel32.GetLastError() == 183: # ERROR_ALREADY_EXISTS
            hwnd = ctypes.windll.user32.FindWindowW(None, "SET DEC TRACKER")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9) # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            sys.exit(0)
            
        # Tell Windows this is a separate app, not just "Python"
        # myappid = 'setdecbot.tracker.app.1' 
        # ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        
        app = QApplication(sys.argv)
        
        # Set App Icon
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon_transparent.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            
        window = MainWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        with open("startup_crash.txt", "w") as f:
            f.write(str(e) + "\n")
            f.write(traceback.format_exc())
        raise e
