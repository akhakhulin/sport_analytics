# PyInstaller spec для сборки sync.exe — один файл, без консольных «хвостов».
# Сборка: запустите `build_exe.cmd` (он зовёт pyinstaller с этим spec).

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(
    ["garmin_sync.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "libsql",
        "garminconnect",
        "garth",
        "dotenv",
        "tqdm",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Тяжёлое и нерелевантное для синка
        "streamlit",
        "plotly",
        "pandas",
        "numpy",
        "matplotlib",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="sync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                # оставляем консольное окно — атлет видит логи и MFA-промпт
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
