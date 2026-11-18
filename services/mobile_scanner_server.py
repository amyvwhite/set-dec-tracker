import os
import sys
import socket
import json
import email
from datetime import datetime
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import io

try:
    import qrcode
    from PIL import Image, ImageOps, ImageEnhance, ImageStat
    HAS_QRCODE = True
    HAS_PIL = True
except ImportError:
    HAS_QRCODE = False
    HAS_PIL = False

def enhance_receipt_image(file_path: str, exposure_mode: str = 'high') -> bool:
    """
    Automatically boosts exposure, contrast, and clarity on receipt photos:
    - Transposes EXIF orientation so portrait phone photos stay right side up
    - Auto-levels/autocontrasts paper background to crisp white
    - Boosts brightness and contrast so faint receipt text is punchy and readable
    - Sharpens text edges for superior OCR and human review
    """
    if not HAS_PIL or not os.path.exists(file_path):
        return False
        
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        return False

    try:
        with Image.open(file_path) as img:
            # 1. Correct EXIF orientation from mobile phone cameras
            img = ImageOps.exif_transpose(img)
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            # If mode is 'normal', only apply orientation and light contrast
            if exposure_mode == 'normal':
                img = ImageOps.autocontrast(img, cutoff=0.5)
                img.save(file_path, 'JPEG', quality=95, optimize=True)
                return True
                
            # 2. Measure initial luminance
            stat = ImageStat.Stat(img.convert('L'))
            avg_lum = stat.mean[0] # 0 = black, 255 = white
            
            # 3. Dynamic exposure boost factors
            if exposure_mode == 'max':
                bright_factor = 1.55 if avg_lum < 160 else 1.30
                contrast_factor = 1.25
                sharp_factor = 1.20
                cutoff = 1.5
            else: # 'high' (default auto)
                bright_factor = 1.35 if avg_lum < 180 else 1.18
                contrast_factor = 1.20
                sharp_factor = 1.15
                cutoff = 1.0

            # 4. Auto-contrast (stretches darkest pixel to black, lightest to crisp white)
            img = ImageOps.autocontrast(img, cutoff=cutoff)
            
            # 5. Brightness boost
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(bright_factor)
            
            # 6. Contrast boost
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(contrast_factor)
            
            # 7. Sharpness boost
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(sharp_factor)
            
            # 8. Save back to file with optimal quality
            img.save(file_path, 'JPEG', quality=95, optimize=True)
            return True
    except Exception as e:
        print(f"DEBUG: Could not enhance exposure for {file_path}: {e}")
        return False

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_destination_paths():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    general_input = os.path.join(base_dir, 'Input')
    
    # Petty cash path (defaults to SAMPLE SHOW S1\PETTY CASH\petty cash input)
    show_dir = os.path.abspath(os.path.join(base_dir, '..', '..'))
    petty_input = os.path.join(show_dir, 'PETTY CASH', 'petty cash input')
    
    # Check if settings overrides exist
    try:
        from core.settings import load_settings
        settings = load_settings()
        general_input = settings.get("general_input_folder") or general_input
        petty_input = settings.get("petty_cash_input_folder") or petty_input
    except Exception:
        pass
        
    os.makedirs(general_input, exist_ok=True)
    os.makedirs(petty_input, exist_ok=True)
    
    return {
        "general": general_input,
        "petty_cash": petty_input
    }

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Set Dec Mobile Scanner</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #0d0f12;
            color: #ffffff;
            min-height: 100vh;
            padding: 16px 16px 100px 16px;
        }
        header {
            text-align: center;
            padding: 12px 0 20px 0;
        }
        .header-title {
            font-size: 20px;
            font-weight: 800;
            letter-spacing: 2px;
            color: #00f2ff;
            text-transform: uppercase;
        }
        .header-subtitle {
            font-size: 12px;
            color: #8892b0;
            margin-top: 4px;
        }
        .dest-card {
            background: #14171d;
            border: 1px solid #232733;
            border-radius: 16px;
            padding: 14px;
            margin-bottom: 20px;
        }
        .section-label {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
            color: #8892b0;
            text-transform: uppercase;
            margin-bottom: 10px;
            display: block;
        }
        .toggle-group {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .toggle-btn {
            background: #1a1e26;
            border: 2px solid #2b3140;
            border-radius: 12px;
            color: #a0aec0;
            padding: 12px 8px;
            font-size: 13px;
            font-weight: bold;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .toggle-btn.active.general {
            background: rgba(0, 242, 255, 0.12);
            border-color: #00f2ff;
            color: #00f2ff;
        }
        .toggle-btn.active.petty {
            background: rgba(210, 179, 255, 0.15);
            border-color: #d2b3ff;
            color: #d2b3ff;
        }
        .toggle-btn .icon {
            font-size: 20px;
            display: block;
            margin-bottom: 4px;
        }
        .buyer-select {
            width: 100%;
            background: #1a1e26;
            border: 1px solid #2b3140;
            border-radius: 10px;
            color: #fff;
            padding: 10px 12px;
            font-size: 14px;
            outline: none;
            margin-top: 6px;
        }
        .exposure-group {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
            margin-top: 6px;
        }
        .exp-btn {
            background: #1a1e26;
            border: 1px solid #2b3140;
            border-radius: 10px;
            color: #8892b0;
            padding: 9px 4px;
            font-size: 11px;
            font-weight: bold;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .exp-btn.active {
            background: rgba(255, 235, 59, 0.15);
            border-color: #ffeb3b;
            color: #fff59d;
        }
        .exp-btn .exp-icon {
            font-size: 16px;
            display: block;
            margin-bottom: 2px;
        }
        .actions-card {
            background: #14171d;
            border: 1px solid #232733;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 20px;
            text-align: center;
        }
        .btn-capture {
            width: 100%;
            background: linear-gradient(135deg, #00f2ff, #0099ff);
            color: #000;
            font-size: 16px;
            font-weight: 800;
            letter-spacing: 1px;
            border: none;
            border-radius: 14px;
            padding: 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            margin-bottom: 12px;
            box-shadow: 0 4px 15px rgba(0, 242, 255, 0.3);
        }
        .btn-capture:active {
            transform: scale(0.98);
        }
        .btn-gallery {
            width: 100%;
            background: #1a1e26;
            color: #e2e8f0;
            border: 1px solid #333d4e;
            border-radius: 14px;
            padding: 14px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn-gallery:active {
            background: #252b36;
        }
        .gallery {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 15px;
        }
        .thumb-box {
            position: relative;
            aspect-ratio: 1;
            border-radius: 10px;
            overflow: hidden;
            background: #222;
            border: 1px solid #333;
        }
        .thumb-box img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .thumb-remove {
            position: absolute;
            top: 4px;
            right: 4px;
            background: rgba(0, 0, 0, 0.7);
            color: #ff4757;
            width: 24px;
            height: 24px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            border: none;
        }
        .bottom-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(13, 15, 18, 0.95);
            backdrop-filter: blur(10px);
            border-top: 1px solid #232733;
            padding: 14px 16px;
            display: flex;
            gap: 10px;
            align-items: center;
            z-index: 100;
        }
        .btn-upload {
            flex: 1;
            background: #00e676;
            color: #000;
            font-size: 15px;
            font-weight: 800;
            letter-spacing: 1px;
            border: none;
            border-radius: 12px;
            padding: 14px;
            cursor: pointer;
            text-align: center;
            transition: all 0.2s;
            box-shadow: 0 4px 12px rgba(0, 230, 118, 0.25);
        }
        .btn-upload:disabled {
            background: #333d4e;
            color: #667284;
            box-shadow: none;
            cursor: not-allowed;
        }
        .btn-clear {
            background: #232733;
            color: #ff6b81;
            border: none;
            border-radius: 12px;
            padding: 14px 16px;
            font-weight: bold;
            font-size: 13px;
            cursor: pointer;
        }
        .status-toast {
            position: fixed;
            top: 16px;
            left: 16px;
            right: 16px;
            background: #00e676;
            color: #000;
            padding: 14px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 14px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            transform: translateY(-150%);
            transition: transform 0.3s ease;
            z-index: 200;
        }
        .status-toast.visible {
            transform: translateY(0);
        }
        .status-toast.error {
            background: #ff4757;
            color: #fff;
        }
        .empty-hint {
            color: #556075;
            font-size: 13px;
            padding: 20px 0;
        }
    </style>
</head>
<body>

    <div id="toast" class="status-toast"></div>

    <header>
        <div class="header-title">Set Dec Scanner</div>
        <div class="header-subtitle">Direct Mobile-to-Desktop Uploader</div>
    </header>

    <div class="dest-card">
        <span class="section-label">1. Choose Destination Folder</span>
        <div class="toggle-group">
            <div id="btn-dest-general" class="toggle-btn active general" onclick="setDestination('general')">
                <span class="icon">💳</span>
                Credit Cards
                <div style="font-size: 10px; font-weight: normal; margin-top: 3px; opacity: 0.8;">Input Folder</div>
            </div>
            <div id="btn-dest-petty" class="toggle-btn petty" onclick="setDestination('petty_cash')">
                <span class="icon">💵</span>
                Petty Cash
                <div style="font-size: 10px; font-weight: normal; margin-top: 3px; opacity: 0.8;">Petty Input Folder</div>
            </div>
        </div>

        <div style="margin-top: 14px;">
            <span class="section-label">Buyer Tag (Optional)</span>
            <select id="buyer-select" class="buyer-select">
                <option value="">-- No Buyer Tag (Default) --</option>
            </select>
        </div>

        <div style="margin-top: 14px;">
            <span class="section-label">Receipt Exposure (Auto-Boost)</span>
            <div class="exposure-group">
                <div id="btn-exp-high" class="exp-btn active" onclick="setExposure('high')">
                    <span class="exp-icon">☀️</span>
                    High Auto
                </div>
                <div id="btn-exp-max" class="exp-btn" onclick="setExposure('max')">
                    <span class="exp-icon">⚡</span>
                    Max Bright
                </div>
                <div id="btn-exp-normal" class="exp-btn" onclick="setExposure('normal')">
                    <span class="exp-icon">📷</span>
                    Standard
                </div>
            </div>
        </div>
    </div>

    <div class="actions-card">
        <span class="section-label">2. Take or Select Photos</span>
        
        <input type="file" id="camera-input" accept="image/*" capture="environment" style="display: none;" onchange="handleFiles(this.files)">
        <input type="file" id="gallery-input" accept="image/*,application/pdf" multiple style="display: none;" onchange="handleFiles(this.files)">

        <button class="btn-capture" onclick="document.getElementById('camera-input').click()">
            <span style="font-size: 20px;">📸</span> SNAP WITH CAMERA
        </button>

        <button class="btn-gallery" onclick="document.getElementById('gallery-input').click()">
            <span>🖼</span> Choose from Photo Library / Files
        </button>

        <div id="gallery" class="gallery"></div>
        <div id="empty-hint" class="empty-hint">No receipts snapped yet</div>
    </div>

    <div class="bottom-bar">
        <button id="btn-clear" class="btn-clear" onclick="clearAll()" style="display: none;">Clear</button>
        <button id="btn-upload" class="btn-upload" onclick="uploadReceipts()" disabled>SELECT PHOTOS TO UPLOAD</button>
    </div>

    <script>
        let currentDestination = 'general';
        let currentExposure = 'high';
        let stagedFiles = [];

        function setDestination(dest) {
            currentDestination = dest;
            document.getElementById('btn-dest-general').className = 'toggle-btn general ' + (dest === 'general' ? 'active' : '');
            document.getElementById('btn-dest-petty').className = 'toggle-btn petty ' + (dest === 'petty_cash' ? 'active' : '');
            updateUploadButton();
        }

        function setExposure(exp) {
            currentExposure = exp;
            document.getElementById('btn-exp-high').className = 'exp-btn ' + (exp === 'high' ? 'active' : '');
            document.getElementById('btn-exp-max').className = 'exp-btn ' + (exp === 'max' ? 'active' : '');
            document.getElementById('btn-exp-normal').className = 'exp-btn ' + (exp === 'normal' ? 'active' : '');
        }

        async function loadServerInfo() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                if (data.buyers && data.buyers.length > 0) {
                    const sel = document.getElementById('buyer-select');
                    data.buyers.forEach(b => {
                        const opt = document.createElement('option');
                        opt.value = b;
                        opt.textContent = b;
                        sel.appendChild(opt);
                    });
                }
            } catch (e) {
                console.log("Could not load server info", e);
            }
        }
        loadServerInfo();

        function handleFiles(files) {
            if (!files || files.length === 0) return;
            for (let i = 0; i < files.length; i++) {
                stagedFiles.push(files[i]);
            }
            renderGallery();
        }

        function renderGallery() {
            const gallery = document.getElementById('gallery');
            const hint = document.getElementById('empty-hint');
            const clearBtn = document.getElementById('btn-clear');
            gallery.innerHTML = '';

            if (stagedFiles.length === 0) {
                hint.style.display = 'block';
                clearBtn.style.display = 'none';
            } else {
                hint.style.display = 'none';
                clearBtn.style.display = 'block';

                stagedFiles.forEach((file, idx) => {
                    const box = document.createElement('div');
                    box.className = 'thumb-box';

                    const img = document.createElement('img');
                    if (file.type.startsWith('image/')) {
                        img.src = URL.createObjectURL(file);
                    } else {
                        img.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100%" height="100%" fill="%23333"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%23fff" font-size="20">PDF</text></svg>';
                    }
                    box.appendChild(img);

                    const removeBtn = document.createElement('button');
                    removeBtn.className = 'thumb-remove';
                    removeBtn.innerHTML = '✕';
                    removeBtn.onclick = (e) => {
                        e.stopPropagation();
                        stagedFiles.splice(idx, 1);
                        renderGallery();
                    };
                    box.appendChild(removeBtn);

                    gallery.appendChild(box);
                });
            }
            updateUploadButton();
        }

        function clearAll() {
            stagedFiles = [];
            renderGallery();
        }

        function updateUploadButton() {
            const btn = document.getElementById('btn-upload');
            const count = stagedFiles.length;
            const destLabel = currentDestination === 'general' ? 'CREDIT CARDS' : 'PETTY CASH';
            if (count > 0) {
                btn.disabled = false;
                btn.textContent = `UPLOAD ${count} TO ${destLabel}`;
            } else {
                btn.disabled = true;
                btn.textContent = 'SELECT PHOTOS TO UPLOAD';
            }
        }

        function showToast(msg, isError = false) {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'status-toast visible ' + (isError ? 'error' : '');
            setTimeout(() => {
                t.className = 'status-toast';
            }, 3500);
        }

        async function uploadReceipts() {
            if (stagedFiles.length === 0) return;
            const btn = document.getElementById('btn-upload');
            btn.disabled = true;
            btn.textContent = 'UPLOADING...';

            const buyer = document.getElementById('buyer-select').value;
            const formData = new FormData();
            formData.append('destination', currentDestination);
            formData.append('buyer', buyer);
            formData.append('exposure', currentExposure);

            stagedFiles.forEach(f => {
                formData.append('files', f);
            });

            try {
                const res = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (navigator.vibrate) navigator.vibrate(200);
                    showToast(`✅ Uploaded ${data.count} receipt(s) directly to ${data.destination}!`);
                    clearAll();
                } else {
                    showToast(`Error: ${data.message || 'Upload failed'}`, true);
                    updateUploadButton();
                }
            } catch (err) {
                showToast(`Upload Error: ${err.message}`, true);
                updateUploadButton();
            }
        }
    </script>
</body>
</html>
"""

class MobileScannerHandler(BaseHTTPRequestHandler):
    server_instance = None

    def log_message(self, format, *args):
        # Quiet standard HTTP request logs
        return

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            return
            
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            buyers = []
            try:
                from core.settings import get_buyers
                buyers = get_buyers()
            except Exception:
                pass
                
            paths = get_destination_paths()
            gen_files = len(os.listdir(paths['general'])) if os.path.exists(paths['general']) else 0
            petty_files = len(os.listdir(paths['petty_cash'])) if os.path.exists(paths['petty_cash']) else 0
            
            resp = {
                "status": "ok",
                "local_ip": get_local_ip(),
                "port": self.server.server_port,
                "buyers": buyers,
                "general_count": gen_files,
                "petty_count": petty_files
            }
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        elif self.path == '/qr':
            if HAS_QRCODE:
                url = f"http://{get_local_ip()}:{self.server.server_port}"
                qr = qrcode.QRCode(box_size=8, border=2)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.end_headers()
                self.wfile.write(buf.getvalue())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/upload':
            try:
                content_type = self.headers.get('Content-Type', '')
                content_length = int(self.headers.get('Content-Length', 0))
                
                body_bytes = self.rfile.read(content_length)
                header_bytes = f"Content-Type: {content_type}\r\n\r\n".encode('utf-8')
                
                msg = email.message_from_bytes(header_bytes + body_bytes)
                
                dest = "general"
                buyer = ""
                exposure = "high"
                files_saved = []
                
                # First pass: find dest, buyer, and exposure fields
                for part in msg.get_payload():
                    name = part.get_param('name', header='content-disposition')
                    if name == 'destination':
                        dest_val = part.get_payload(decode=True)
                        if dest_val:
                            dest = dest_val.decode('utf-8', errors='ignore').strip()
                    elif name == 'buyer':
                        buyer_val = part.get_payload(decode=True)
                        if buyer_val:
                            buyer = buyer_val.decode('utf-8', errors='ignore').strip()
                    elif name == 'exposure':
                        exp_val = part.get_payload(decode=True)
                        if exp_val:
                            exposure = exp_val.decode('utf-8', errors='ignore').strip().lower()
                
                paths = get_destination_paths()
                target_dir = paths.get(dest, paths['general'])
                dest_label = "Credit Cards (Input)" if dest == 'general' else "Petty Cash (petty cash input)"
                
                # Second pass: save uploaded files
                now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                for idx, part in enumerate(msg.get_payload()):
                    filename = part.get_filename()
                    if filename:
                        raw_data = part.get_payload(decode=True)
                        if not raw_data:
                            continue
                        
                        ext = os.path.splitext(filename)[1]
                        if not ext:
                            ext = '.jpg'
                            
                        clean_name = os.path.splitext(os.path.basename(filename))[0]
                        prefix = f"{buyer.upper()}_" if buyer else ""
                        save_filename = f"{prefix}{now_str}_{idx+1}_{clean_name}{ext}"
                        save_path = os.path.join(target_dir, save_filename)
                        
                        with open(save_path, 'wb') as f:
                            f.write(raw_data)
                            
                        # Automatically enhance exposure, contrast & auto-orient photo
                        enhance_receipt_image(save_path, exposure_mode=exposure)
                            
                        files_saved.append(save_filename)
                        
                        if MobileScannerHandler.server_instance and hasattr(MobileScannerHandler.server_instance, 'on_file_received'):
                            MobileScannerHandler.server_instance.on_file_received(save_filename, dest_label)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                resp = {
                    "status": "success",
                    "count": len(files_saved),
                    "destination": dest_label,
                    "files": files_saved
                }
                self.wfile.write(json.dumps(resp).encode('utf-8'))
                return

            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                resp = {"status": "error", "message": str(e)}
                self.wfile.write(json.dumps(resp).encode('utf-8'))
                return

        self.send_response(404)
        self.end_headers()

class MobileScannerServer:
    def __init__(self, port=5050):
        self.port = port
        self.server = None
        self.thread = None
        self._is_running = False
        self.callbacks = []

    def register_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def on_file_received(self, filename, destination):
        for cb in self.callbacks:
            try:
                cb(filename, destination)
            except Exception as e:
                print("DEBUG: Callback error:", e)

    def start(self):
        if self._is_running:
            return True
        try:
            MobileScannerHandler.server_instance = self
            # Bind to all interfaces (0.0.0.0) so phone on local Wi-Fi can reach it
            self.server = ThreadingHTTPServer(('0.0.0.0', self.port), MobileScannerHandler)
            self._is_running = True
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            print(f"Mobile Scanner Server running at: http://{get_local_ip()}:{self.port}")
            return True
        except Exception as e:
            print(f"ERROR: Could not start Mobile Scanner Server: {e}")
            self._is_running = False
            return False

    def stop(self):
        if self.server and self._is_running:
            self.server.shutdown()
            self.server.server_close()
            self._is_running = False
            print("Mobile Scanner Server stopped.")

    def is_running(self):
        return self._is_running

    def get_url(self):
        return f"http://{get_local_ip()}:{self.port}"

# Global singleton
_scanner_server = None

def get_scanner_server(port=5050):
    global _scanner_server
    if _scanner_server is None:
        _scanner_server = MobileScannerServer(port=port)
    return _scanner_server
