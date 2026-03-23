# -*- mode: python ; coding: utf-8 -*-
"""
DubSync Pro — PyInstaller Spec Dosyası

Tek EXE üretir (--onefile).
Torch + XTTS dahil (~1-2GB).
Settings dosyasını EXE yanına kopyalayın.

Kullanım:
    pyinstaller dubsync_pro.spec
"""

import sys
import os

block_cipher = None

# Proje kök dizini
PROJE_DIZIN = os.path.abspath('.')

a = Analysis(
    ['main.py'],
    pathex=[PROJE_DIZIN],
    binaries=[],
    datas=[
        # Settings dosyasını EXE'nin temp klasörüne dahil etme —
        # kullanıcı EXE yanına kendi settings'ini koyacak.
        # İlk çalıştırmada otomatik oluşturulur (ConfigManager varsayılanları).
    ],
    hiddenimports=[
        # Core modüller
        'core',
        'core.config_manager',
        'core.srt_parser',
        'core.tts_manager',
        'core.timing_analyzer',
        'core.time_stretcher',
        'core.audio_assembler',
        'core.audio_ducker',
        'core.video_exporter',

        # Engine modüller
        'engines',
        'engines.base_engine',
        'engines.edge_engine',
        'engines.openai_engine',
        'engines.elevenlabs_engine',
        'engines.xtts_engine',

        # GUI modüller
        'gui',
        'gui.main_window',
        'gui.character_panel',
        'gui.subtitle_table',
        'gui.settings_panel',
        'gui.ducking_panel',
        'gui.preview_player',

        # Üçüncü parti — PyInstaller bazen kaçırır
        'edge_tts',
        'edge_tts.communicate',
        'pysrt',
        'chardet',
        'aiohttp',
        'soundfile',
        'librosa',
        'librosa.core',
        'librosa.effects',
        'pydub',
        'numpy',
        'numpy.core',

        # Torch + XTTS
        'torch',
        'torchaudio',
        'TTS',
        'TTS.api',
        'TTS.tts',
        'TTS.tts.configs.xtts_config',
        'TTS.tts.models.xtts',

        # OpenAI / ElevenLabs (opsiyonel, yüklüyse)
        'openai',
        'elevenlabs',
        'elevenlabs.client',

        # PyQt6
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Gereksiz büyük paketler
        'matplotlib',
        'tkinter',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sphinx',
        'setuptools',
        'pip',
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
    name='DubSync_Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # GUI uygulaması — konsol penceresi açılmaz
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='dubsync_pro.ico',  # İkon dosyanız varsa aktif edin
)
