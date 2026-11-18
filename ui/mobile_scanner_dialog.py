import os
import io
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QMessageBox, QApplication
)
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from services.mobile_scanner_server import get_scanner_server, get_local_ip, get_destination_paths

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

class ServerSignalBridge(QObject):
    file_received = Signal(str, str)

class MobileScannerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mobile Phone Scanner - Set Dec Tracker")
        self.setFixedSize(540, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #0d0f12;
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #e2e8f0;
            }
            QPushButton {
                background-color: rgba(20, 20, 20, 0.7);
                border: 1px solid #3b82f6;
                border-radius: 10px;
                color: #60a5fa;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 0.2);
                border: 1px solid #60a5fa;
                color: #ffffff;
            }
            QListWidget {
                background-color: #14171d;
                border: 1px solid #232733;
                border-radius: 10px;
                color: #cbd5e1;
                font-size: 11px;
                padding: 6px;
            }
        """)

        self.server = get_scanner_server(port=5050)
        self.bridge = ServerSignalBridge()
        self.bridge.file_received.connect(self.on_file_received_ui)
        self.server.register_callback(self.bridge.file_received.emit)

        if not self.server.is_running():
            self.server.start()

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # Header
        header = QLabel("📱 MOBILE PHONE SCANNER")
        header.setStyleSheet("color: #00f2ff; font-size: 15px; font-weight: 800; letter-spacing: 2px;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        sub = QLabel("Scan the QR code with your phone camera to snap & upload receipts directly to your folders.")
        sub.setStyleSheet("color: #8892b0; font-size: 12px;")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # QR Code Display Frame
        qr_frame = QFrame()
        qr_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 4px solid #232733;
                border-radius: 16px;
            }
        """)
        qr_frame.setFixedSize(220, 220)
        qr_layout = QVBoxLayout(qr_frame)
        qr_layout.setContentsMargins(10, 10, 10, 10)
        qr_layout.setAlignment(Qt.AlignCenter)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(self.qr_label)

        # Center QR frame horizontally
        qr_container = QHBoxLayout()
        qr_container.setAlignment(Qt.AlignCenter)
        qr_container.addWidget(qr_frame)
        layout.addLayout(qr_container)

        self.render_qr_code()

        # URL and Copy link
        url_layout = QHBoxLayout()
        url_layout.setAlignment(Qt.AlignCenter)
        url_layout.setSpacing(10)

        url_str = self.server.get_url()
        self.url_label = QLabel(url_str)
        self.url_label.setStyleSheet("color: #00e676; font-size: 13px; font-weight: bold; background: #14171d; padding: 6px 12px; border-radius: 8px; border: 1px solid #232733;")
        url_layout.addWidget(self.url_label)

        copy_btn = QPushButton("📋 Copy Link")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(self.copy_url)
        url_layout.addWidget(copy_btn)

        layout.addLayout(url_layout)

        # Destination Folders Status
        paths = get_destination_paths()
        paths_frame = QFrame()
        paths_frame.setStyleSheet("background: #14171d; border: 1px solid #232733; border-radius: 10px; padding: 10px;")
        paths_layout = QVBoxLayout(paths_frame)
        paths_layout.setSpacing(6)

        gen_count = len(os.listdir(paths['general'])) if os.path.exists(paths['general']) else 0
        petty_count = len(os.listdir(paths['petty_cash'])) if os.path.exists(paths['petty_cash']) else 0

        self.gen_label = QLabel(f"💳 Credit Cards Input Folder:  <b>{gen_count}</b> files ready")
        self.gen_label.setStyleSheet("color: #80dfff; font-size: 11px;")
        paths_layout.addWidget(self.gen_label)

        self.petty_label = QLabel(f"💵 Petty Cash Input Folder:  <b>{petty_count}</b> files ready")
        self.petty_label.setStyleSheet("color: #d2b3ff; font-size: 11px;")
        paths_layout.addWidget(self.petty_label)

        layout.addWidget(paths_frame)

        # Live incoming feed
        lbl_feed = QLabel("LIVE ACTIVITY FEED")
        lbl_feed.setStyleSheet("color: #8892b0; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")
        layout.addWidget(lbl_feed)

        self.feed_list = QListWidget()
        self.feed_list.setFixedHeight(110)
        layout.addWidget(self.feed_list)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        open_general_btn = QPushButton("📂 Open Credit Cards Folder")
        open_general_btn.clicked.connect(lambda: self.open_folder(paths['general']))
        btn_layout.addWidget(open_general_btn)

        open_petty_btn = QPushButton("📂 Open Petty Cash Folder")
        open_petty_btn.clicked.connect(lambda: self.open_folder(paths['petty_cash']))
        btn_layout.addWidget(open_petty_btn)

        layout.addLayout(btn_layout)

    def render_qr_code(self):
        url = self.server.get_url()
        if HAS_QR:
            qr = qrcode.QRCode(box_size=10, border=1)
            qr.add_data(url)
            qr.make(fit=True)
            pil_img = qr.make_image(fill_color="#000000", back_color="#ffffff")
            buf = io.BytesIO()
            pil_img.save(buf, format='PNG')
            buf.seek(0)
            qimg = QImage.fromData(buf.getvalue())
            pixmap = QPixmap.fromImage(qimg).scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.qr_label.setPixmap(pixmap)
        else:
            self.qr_label.setText(f"QR Generator\nAvailable at:\n{url}")
            self.qr_label.setStyleSheet("color: #000; font-size: 12px; font-weight: bold;")

    def copy_url(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.server.get_url())
        QMessageBox.information(self, "Copied", f"Link copied to clipboard:\n{self.server.get_url()}")

    def open_folder(self, path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Not Found", f"Folder does not exist yet:\n{path}")

    def on_file_received_ui(self, filename, destination):
        from datetime import datetime
        time_str = datetime.now().strftime("%I:%M:%S %p")
        item = QListWidgetItem(f"[{time_str}] 📥 {filename}  ➔  {destination}")
        item.setForeground(Qt.green if "Credit" in destination else Qt.magenta)
        self.feed_list.insertItem(0, item)
        self.refresh_counts()

    def refresh_counts(self):
        paths = get_destination_paths()
        gen_count = len(os.listdir(paths['general'])) if os.path.exists(paths['general']) else 0
        petty_count = len(os.listdir(paths['petty_cash'])) if os.path.exists(paths['petty_cash']) else 0
        self.gen_label.setText(f"💳 Credit Cards Input Folder:  <b>{gen_count}</b> files ready")
        self.petty_label.setText(f"💵 Petty Cash Input Folder:  <b>{petty_count}</b> files ready")
