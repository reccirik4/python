# -*- coding: utf-8 -*-
"""
DubSync Pro - torchcodec Windows Fix

Sorun: torchcodec + nightly torch Windows'ta WinError 87 veriyor.
Cozum: torchcodec'i kaldir + TTS paketinin zorunluluk kontrolunu bypass et.

Kullanim:
    cd C:\\kodlamalar\\python\\srt-tts-2026-super-gpu
    python patch_torchcodec_fix.py
"""

import os
import sys
import shutil
import subprocess
import site
from datetime import datetime
from pathlib import Path


def tts_init_bul():
    """TTS paketinin __init__.py dosyasini bulur."""
    # venv'deki site-packages
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        init = os.path.join(sp, "TTS", "__init__.py")
        if os.path.isfile(init):
            return init

    # sys.path'ten ara
    for p in sys.path:
        init = os.path.join(p, "TTS", "__init__.py")
        if os.path.isfile(init):
            return init

    return None


def main():
    print("=" * 60)
    print("DubSync Pro — torchcodec Windows Fix")
    print("=" * 60)

    # 1. torchcodec'i kaldir
    print("\n1. torchcodec kaldiriliyor...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "torchcodec", "-y"],
        capture_output=True, text=True
    )
    if "Successfully" in result.stdout:
        print("   ✅ torchcodec kaldirildi.")
    elif "not installed" in result.stdout.lower() or "WARNING: Skipping" in result.stdout:
        print("   ⏭️  torchcodec zaten kurulu degil.")
    else:
        print(f"   ℹ️  {result.stdout.strip()}")

    # 2. TTS/__init__.py'deki torchcodec kontrolunu bypass et
    print("\n2. TTS/__init__.py torchcodec kontrolu bypass ediliyor...")

    init_yolu = tts_init_bul()
    if not init_yolu:
        print("   ❌ TTS paketi bulunamadi!")
        print("   Kurulum: pip install coqui-tts==0.27.5")
        sys.exit(1)

    print(f"   Dosya: {init_yolu}")

    with open(init_yolu, "r", encoding="utf-8") as f:
        icerik = f.read()

    # Zaten fix uygulanmis mi?
    if "# DUBSYNC_TORCHCODEC_FIX" in icerik:
        print("   ⏭️  Fix zaten uygulanmis.")
    elif "TORCHCODEC_IMPORT_ERROR" in icerik:
        # Yedek al
        yedek = init_yolu + f".bak_{datetime.now().strftime('%H%M%S')}"
        shutil.copy2(init_yolu, yedek)
        print(f"   Yedek: {yedek}")

        # raise ImportError(TORCHCODEC_IMPORT_ERROR) satirini
        # pass ile degistir
        icerik = icerik.replace(
            "raise ImportError(TORCHCODEC_IMPORT_ERROR)",
            "pass  # DUBSYNC_TORCHCODEC_FIX — Windows WinError 87 fix"
        )

        with open(init_yolu, "w", encoding="utf-8") as f:
            f.write(icerik)

        print("   ✅ torchcodec kontrolu devre disi birakildi.")
    else:
        print("   ℹ️  TORCHCODEC_IMPORT_ERROR bulunamadi — kontrol yok veya farkli versiyon.")

    # 3. Test
    print("\n3. Import testi...")
    try:
        # Onceki import'lari temizle
        for mod in list(sys.modules.keys()):
            if mod.startswith("TTS") or mod == "torchcodec":
                del sys.modules[mod]

        result = subprocess.run(
            [sys.executable, "-c", "from TTS.api import TTS; print('OK')"],
            capture_output=True, text=True, timeout=60
        )
        if "OK" in result.stdout:
            print("   ✅ from TTS.api import TTS → OK")
        else:
            stderr = result.stderr.strip()[-200:] if result.stderr else ""
            print(f"   ❌ Import hatasi: {stderr}")
    except Exception as e:
        print(f"   ❌ Test hatasi: {e}")

    print("\n" + "=" * 60)
    print("Simdi test et:")
    print("  python main.py --debug")
    print("=" * 60)


if __name__ == "__main__":
    main()
