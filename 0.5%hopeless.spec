# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ('Sample output/Sample-keynote1.key', 'Sample output'),
    ('Sample output/Sample-keynote2.key', 'Sample output'),
    ('Sample output/Sample-keynote3.key', 'Sample output'),
    ('assets/app_icon.png', 'assets'),
]
binaries = []
hiddenimports = [
    'customtkinter',
    'tkinterdnd2',
    'keynote_parser',
    'openpyxl',
    'pandas',
    'requests',
    'snappy',
    'PIL',
    'PIL.Image',
]

# Collect all resources from customtkinter, tkinterdnd2, keynote_parser
for pkg in ['customtkinter', 'tkinterdnd2', 'keynote_parser']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='0.5%hopeless',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='0.5%hopeless',
)

app = BUNDLE(
    coll,
    name='0.5%hopeless.app',
    icon='assets/app_icon.icns',
    bundle_identifier='com.apple.manufacturing.hopeless',
    info_plist={
        'CFBundleDisplayName': '0.5%hopeless',
        'CFBundleName': '0.5%hopeless',
        'CFBundleIdentifier': 'com.apple.manufacturing.hopeless',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSAppleEventsUsageDescription': 'Ứng dụng cần quyền điều khiển Keynote để tự động tạo và xuất báo cáo slide.',
        'LSEnvironment': {
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
        }
    }
)
