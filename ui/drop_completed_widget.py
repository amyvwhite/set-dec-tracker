import os
import subprocess
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QMessageBox, QApplication
from PySide6.QtCore import Qt, Signal
from services.completed_agreements_service import process_dropped_files

class DropCompletedAgreementsWidget(QFrame):
    completed_processed = Signal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropCompletedWidget")
        self.setAcceptDrops(True)
        self.setFixedSize(260, 50)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QFrame#DropCompletedWidget {
                background-color: rgba(0, 255, 136, 0.05);
                border: 2px dashed #00ff88;
                border-radius: 12px;
            }
            QFrame#DropCompletedWidget:hover {
                background-color: rgba(0, 255, 136, 0.15);
                border-style: solid;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        self.label = QLabel("📥 DROP COMPLETED HERE")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #00ff88; font-size: 10px; font-weight: bold; letter-spacing: 1px; border: none; background: transparent;")

        self.sublabel = QLabel("Auto-renames & moves to Completed folder")
        self.sublabel.setAlignment(Qt.AlignCenter)
        self.sublabel.setStyleSheet("color: #888888; font-size: 9px; border: none; background: transparent;")

        layout.addWidget(self.label)
        layout.addWidget(self.sublabel)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        files = [url.toLocalFile() for url in urls if url.toLocalFile().lower().endswith('.pdf')]

        if files:
            orig_text = self.label.text()
            self.label.setText("⏳ READING SCAN WITH AI...")
            QApplication.processEvents()

            try:
                count, results = process_dropped_files(files)
            finally:
                self.label.setText(orig_text)
            
            if count > 0:
                from services.completed_agreements_service import get_default_agreements_dir
                completed_dir = os.path.join(get_default_agreements_dir(), "completed")
                msg_text = f"Successfully organized {count} completed agreement(s):\n\n"
                for orig, new_name in results:
                    msg_text += f"• {orig} ➔ {new_name}\n"

                msg = QMessageBox(self)
                msg.setWindowTitle("Agreements Organized")
                msg.setText(msg_text)
                msg.setIcon(QMessageBox.Information)

                btn_open_folder = msg.addButton("Open Completed Folder", QMessageBox.ActionRole)
                btn_ok = msg.addButton("OK", QMessageBox.AcceptRole)
                msg.exec()

                if msg.clickedButton() == btn_open_folder:
                    if os.name == 'nt':
                        os.startfile(completed_dir)
                    else:
                        subprocess.run(['open', completed_dir])

            else:
                QMessageBox.information(self, "No Changes Needed", "The dropped agreement(s) are already organized in the Completed folder!")
