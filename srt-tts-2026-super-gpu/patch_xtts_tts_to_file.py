# -*- coding: utf-8 -*-
"""
DubSync Pro — XTTS tts_to_file Windows Fix

Sorun: tts_to_file + torchcodec + nightly torch → [WinError 87] Parametre hatalı: '.'
Çözüm: tts_to_file yerine tts() + soundfile.write kullan

Kullanım:
    cd C:\kodlamalar\python\srt-tts-2026-super-gpu
    python patch_xtts_tts_to_file.py
"""

import os
import sys
import shutil
from datetime import datetime


def patch_dosya(dosya_yolu, eski, yeni, aciklama):
    if not os.path.isfile(dosya_yolu):
        print(f"  ❌ Dosya bulunamadı: {dosya_yolu}")
        return False

    with open(dosya_yolu, "r", encoding="utf-8") as f:
        icerik = f.read()

    if eski not in icerik:
        if yeni in icerik:
            print(f"  ⏭️  Zaten uygulanmış: {aciklama}")
            return True
        print(f"  ❌ Eşleşme bulunamadı: {aciklama}")
        return False

    yedek = dosya_yolu + f".bak_{datetime.now().strftime('%H%M%S')}"
    shutil.copy2(dosya_yolu, yedek)

    icerik = icerik.replace(eski, yeni, 1)

    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write(icerik)

    print(f"  ✅ {aciklama}")
    return True


def main():
    if not os.path.isdir("engines"):
        print("❌ Bu scripti proje kök dizininde çalıştırın!")
        sys.exit(1)

    print("=" * 60)
    print("DubSync Pro — XTTS Windows Fix (tts_to_file → tts+sf)")
    print("=" * 60)

    basarili = 0
    toplam = 0

    print("\n📁 engines/xtts_engine.py")

    # PATCH: tts_to_file → tts() + soundfile.write
    toplam += 1
    ok = patch_dosya(
        "engines/xtts_engine.py",
        # ESKİ
        '''        try:
            self._tts.tts_to_file(
                text=metin,
                speaker_wav=referans_yolu,
                language=self._dil,
                file_path=cikis_yolu,
            )

            if not os.path.isfile(cikis_yolu):
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="XTTS ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            sure_ms = self.ses_suresi_hesapla(cikis_yolu)''',
        # YENİ
        '''        try:
            # tts_to_file yerine tts() + soundfile.write
            # (torchcodec + nightly torch Windows'ta WinError 87 veriyor)
            import numpy as np
            import soundfile as sf

            wav = self._tts.tts(
                text=metin,
                speaker_wav=referans_yolu,
                language=self._dil,
            )

            # Liste veya tensor → numpy array
            if not isinstance(wav, np.ndarray):
                wav = np.array(wav, dtype=np.float32)

            # Normalize (clipping önleme)
            peak = np.max(np.abs(wav))
            if peak > 0.99:
                wav = wav * (0.95 / peak)

            sf.write(cikis_yolu, wav, 24000, subtype="PCM_24")

            if not os.path.isfile(cikis_yolu):
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="XTTS ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            sure_ms = self.ses_suresi_hesapla(cikis_yolu)''',
        "tts_to_file → tts() + soundfile.write (Windows fix)",
    )
    if ok:
        basarili += 1

    print("\n" + "=" * 60)
    if basarili == toplam:
        print(f"✅ Patch başarılı! ({basarili}/{toplam})")
        print("\nTest et:")
        print("  python main.py --debug")
    else:
        print(f"⚠️  {basarili}/{toplam} patch uygulandı.")
    print("=" * 60)


if __name__ == "__main__":
    main()
