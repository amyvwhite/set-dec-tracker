import subprocess
import sys
import os

def main():
    target_dir = os.path.dirname(os.path.abspath(__file__))
    pythonw = "pythonw.exe"
    
    script = os.path.join(target_dir, "app.py")
    
    # Launch it
    subprocess.Popen([pythonw, script], cwd=target_dir)

if __name__ == "__main__":
    main()
