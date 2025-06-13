# This spec file is ONLY for building the Windows version via GitHub Actions.
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('bin/ffmpeg.exe', 'bin'),
        ('ui/loading-7528.gif', 'ui'),
        *collect_data_files('lightning_fabric'),
        *collect_data_files('speechbrain'),
        *collect_data_files('pyannote')
    ],
    hiddenimports=[
        'torch',
        'torchaudio',
        'speechbrain',
        'pyannote',
        'pandas',
        'sklearn',
        'tiktoken'
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=['win_pre_init_hook.py'],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Transcription_dev_test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
