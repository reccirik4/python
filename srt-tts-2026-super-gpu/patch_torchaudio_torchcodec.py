# -*- coding: utf-8 -*-
"""
DubSync Pro - torchaudio torchcodec -> soundfile Patch

Sorun: torchaudio 2.12 nightly, load_with_torchcodec icinde
       torchcodec.decoders.AudioDecoder kullaniyor.
       Windows'ta WinError 87 veriyor.

Cozum: torchaudio/_torchcodec.py icindeki load_with_torchcodec
       fonksiyonunu soundfile backend ile degistir.

Kullanim:
    cd C:\\kodlamalar\\python\\srt-tts-2026-super-gpu
    python patch_torchaudio_torchcodec.py
    python main.py --debug
"""

import os
import sys
import shutil
from datetime import datetime


HEDEF = os.path.join("venv", "Lib", "site-packages", "torchaudio", "_torchcodec.py")

YENI_LOAD = '''def load_with_torchcodec(
    uri,
    frame_offset: int = 0,
    num_frames: int = -1,
    normalize: bool = True,
    channels_first: bool = True,
    format=None,
    buffer_size: int = 4096,
    backend=None,
):
    """Patched: soundfile backend (torchcodec Windows nightly fix)."""
    import soundfile as sf
    import numpy as np

    data, sample_rate = sf.read(uri, dtype="float32", always_2d=True)
    # data shape: [frames, channels]

    # frame_offset ve num_frames uygula
    if frame_offset > 0:
        if frame_offset >= data.shape[0]:
            empty_shape = (data.shape[1], 0) if channels_first else (0, data.shape[1])
            return torch.zeros(empty_shape, dtype=torch.float32), sample_rate
        data = data[frame_offset:]

    if num_frames == 0:
        empty_shape = (data.shape[1], 0) if channels_first else (0, data.shape[1])
        return torch.zeros(empty_shape, dtype=torch.float32), sample_rate
    elif num_frames > 0:
        data = data[:num_frames]

    wav = torch.from_numpy(data.copy())  # [frames, channels]

    if channels_first:
        wav = wav.transpose(0, 1)  # [channels, frames]

    return wav, sample_rate'''


def main():
    if not os.path.isfile(HEDEF):
        print(f"HATA: Dosya bulunamadi: {HEDEF}")
        sys.exit(1)

    print("=" * 60)
    print("DubSync Pro - torchaudio torchcodec Patch")
    print("=" * 60)
    print(f"\nHedef: {HEDEF}")

    with open(HEDEF, "r", encoding="utf-8") as f:
        icerik = f.read()

    # Zaten patch edilmis mi?
    if "# Patched: soundfile backend" in icerik or "soundfile backend (torchcodec Windows nightly fix)" in icerik:
        print("\nZaten patch edilmis!")
        print("=" * 60)
        return

    # Yedek al
    yedek = HEDEF + f".bak_{datetime.now().strftime('%H%M%S')}"
    shutil.copy2(HEDEF, yedek)
    print(f"Yedek: {yedek}")

    # load_with_torchcodec fonksiyonunu bul ve degistir
    marker = "def load_with_torchcodec("
    if marker not in icerik:
        print(f"\nHATA: '{marker}' bulunamadi!")
        sys.exit(1)

    # save_with_torchcodec fonksiyonunu bul — load oraya kadar
    save_marker = "def save_with_torchcodec("
    if save_marker not in icerik:
        print(f"\nHATA: '{save_marker}' bulunamadi!")
        sys.exit(1)

    load_start = icerik.index(marker)
    save_start = icerik.index(save_marker)

    # load fonksiyonundan onceki kisim + yeni load + save'den itibaren devam
    onceki = icerik[:load_start]
    sonraki = icerik[save_start:]

    yeni_icerik = onceki + YENI_LOAD + "\n\n\n" + sonraki

    with open(HEDEF, "w", encoding="utf-8") as f:
        f.write(yeni_icerik)

    print("\n✅ load_with_torchcodec -> soundfile backend ile degistirildi!")

    # Test
    print("\nImport testi...")
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         "import torchaudio; print('torchaudio OK'); "
         "from TTS.api import TTS; print('TTS OK')"],
        capture_output=True, text=True, timeout=60
    )
    if "torchaudio OK" in result.stdout:
        print("  ✅ torchaudio import OK")
    else:
        print(f"  ❌ torchaudio hatasi: {result.stderr[-200:]}")

    if "TTS OK" in result.stdout:
        print("  ✅ TTS import OK")
    else:
        print(f"  ❌ TTS hatasi: {result.stderr[-200:]}")

    print("\n" + "=" * 60)
    print("Test: python main.py --debug")
    print("=" * 60)


if __name__ == "__main__":
    main()
