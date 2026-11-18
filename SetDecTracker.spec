# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None
app_dir = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(app_dir, 'assets'), 'assets'),
]

# Include default settings.json template if present
if os.path.exists(os.path.join(app_dir, 'settings.json')):
    datas.append((os.path.join(app_dir, 'settings.json'), '.'))

# Include services template files and credentials if present
template_json = os.path.join(app_dir, 'services', 'template.json')
if os.path.exists(template_json):
    datas.append((template_json, 'services'))

creds_json = os.path.join(app_dir, 'services', 'credentials.json')
if os.path.exists(creds_json):
    datas.append((creds_json, 'services'))

a = Analysis(
    [os.path.join(app_dir, 'app.py')],
    pathex=[app_dir],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'fitz',
        'google.oauth2',
        'google.oauth2.service_account',
        'google.auth',
        'gspread',
        'win32com.client',
        'PIL',
        'sqlite3',
        'dateutil',
        'core',
        'services',
        'services.mobile_scanner_server',
        'qrcode',
        'ui'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Set Dec Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(app_dir, 'assets', 'icon.ico') if os.path.exists(os.path.join(app_dir, 'assets', 'icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Set Dec Tracker',
)
