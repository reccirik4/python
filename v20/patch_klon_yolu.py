# -*- coding: utf-8 -*-
"""
DubSync Pro — klon_yolu Patch Scripti
3 dosyada klon_yolu desteği ekler.

Kullanım:
    python patch_klon_yolu.py

Değiştirilen dosyalar:
    1. core/config_manager.py  → karakter_ekle'ye klon_yolu parametresi
    2. gui/character_panel.py  → config_e_kaydet'te klon_yolu gönderimi
    3. core/tts_manager.py     → karakter_icin_motor_ve_ses'te klon_yolu desteği
"""

import os
import sys
import shutil
from datetime import datetime


def patch_dosya(dosya_yolu: str, eski: str, yeni: str, aciklama: str) -> bool:
    """Dosyada str_replace yapar."""
    if not os.path.isfile(dosya_yolu):
        print(f"  ❌ HATA: Dosya bulunamadı: {dosya_yolu}")
        return False

    with open(dosya_yolu, "r", encoding="utf-8") as f:
        icerik = f.read()

    if eski not in icerik:
        if yeni in icerik:
            print(f"  ⏭️  Zaten uygulanmış: {aciklama}")
            return True
        print(f"  ❌ HATA: Eşleşme bulunamadı: {aciklama}")
        print(f"     Aranan (ilk 80 karakter): {eski[:80]}...")
        return False

    # Yedek al
    yedek = dosya_yolu + f".bak_{datetime.now().strftime('%H%M%S')}"
    shutil.copy2(dosya_yolu, yedek)

    icerik = icerik.replace(eski, yeni, 1)

    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write(icerik)

    print(f"  ✅ {aciklama}")
    return True


def main():
    # Proje kök dizininde çalıştığımızı kontrol et
    if not os.path.isdir("core") or not os.path.isdir("gui"):
        print("❌ Bu scripti proje kök dizininde çalıştırın!")
        print("   (core/ ve gui/ klasörlerinin olduğu dizin)")
        sys.exit(1)

    print("=" * 60)
    print("DubSync Pro — klon_yolu Patch")
    print("=" * 60)
    basarili = 0
    toplam = 0

    # ─────────────────────────────────────────────────────
    # PATCH 1: core/config_manager.py
    # karakter_ekle fonksiyonuna klon_yolu parametresi ekle
    # ─────────────────────────────────────────────────────
    print("\n📁 core/config_manager.py")

    # 1a: Fonksiyon imzasına klon_yolu ekle
    toplam += 1
    ok = patch_dosya(
        "core/config_manager.py",
        # ESKİ
        '''    def karakter_ekle(
        self,
        karakter_id: str,
        isim: str = "",
        motor: str = "",
        ses: str = "",
        cinsiyet: str = "erkek",
        hiz: str = "+0%",
        perde: str = "+0Hz",
    ) -> None:''',
        # YENİ
        '''    def karakter_ekle(
        self,
        karakter_id: str,
        isim: str = "",
        motor: str = "",
        ses: str = "",
        cinsiyet: str = "erkek",
        hiz: str = "+0%",
        perde: str = "+0Hz",
        klon_yolu: str = "",
    ) -> None:''',
        "karakter_ekle imzasına klon_yolu parametresi eklendi",
    )
    if ok:
        basarili += 1

    # 1b: Dict'e klon_yolu ekle
    toplam += 1
    ok = patch_dosya(
        "core/config_manager.py",
        # ESKİ
        '''        self._ayarlar["karakterler"][karakter_id] = {
            "isim": isim,
            "motor": motor,
            "ses": ses,
            "cinsiyet": cinsiyet,
            "hiz": hiz,
            "perde": perde,
        }''',
        # YENİ
        '''        self._ayarlar["karakterler"][karakter_id] = {
            "isim": isim,
            "motor": motor,
            "ses": ses,
            "cinsiyet": cinsiyet,
            "hiz": hiz,
            "perde": perde,
            "klon_yolu": klon_yolu,
        }''',
        "karakter dict'ine klon_yolu alanı eklendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # PATCH 2: gui/character_panel.py
    # config_e_kaydet fonksiyonunda klon_yolu gönder
    # ─────────────────────────────────────────────────────
    print("\n📁 gui/character_panel.py")

    toplam += 1
    ok = patch_dosya(
        "gui/character_panel.py",
        # ESKİ
        '''    def config_e_kaydet(self, config: ConfigManager):
        """Tüm karakter verilerini ConfigManager'a kaydeder."""
        for karakter_id, kart in self._kartlar.items():
            veri = kart.veri_al()
            config.karakter_ekle(
                karakter_id=karakter_id,
                isim=veri.get("isim", ""),
                motor=veri.get("motor", ""),
                ses=veri.get("ses", ""),
                cinsiyet=veri.get("cinsiyet", "erkek"),
                hiz=veri.get("hiz", "+0%"),
                perde=veri.get("perde", "+0Hz"),
            )''',
        # YENİ
        '''    def config_e_kaydet(self, config: ConfigManager):
        """Tüm karakter verilerini ConfigManager'a kaydeder."""
        for karakter_id, kart in self._kartlar.items():
            veri = kart.veri_al()
            config.karakter_ekle(
                karakter_id=karakter_id,
                isim=veri.get("isim", ""),
                motor=veri.get("motor", ""),
                ses=veri.get("ses", ""),
                cinsiyet=veri.get("cinsiyet", "erkek"),
                hiz=veri.get("hiz", "+0%"),
                perde=veri.get("perde", "+0Hz"),
                klon_yolu=veri.get("klon_yolu", ""),
            )''',
        "config_e_kaydet'e klon_yolu gönderimi eklendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # PATCH 3: core/tts_manager.py
    # karakter_icin_motor_ve_ses'te klon_yolu desteği
    # ─────────────────────────────────────────────────────
    print("\n📁 core/tts_manager.py")

    # 3a: ek dict'ine klon_yolu ekle (karakter varsa)
    toplam += 1
    ok = patch_dosya(
        "core/tts_manager.py",
        # ESKİ
        '''        if karakter:
            motor_adi = karakter.get("motor", "")
            ses_id = karakter.get("ses", "")
            ek = {
                "hiz": karakter.get("hiz", "+0%"),
                "perde": karakter.get("perde", "+0Hz"),
            }''',
        # YENİ
        '''        if karakter:
            motor_adi = karakter.get("motor", "")
            ses_id = karakter.get("ses", "")
            klon_yolu = karakter.get("klon_yolu", "")
            ek = {
                "hiz": karakter.get("hiz", "+0%"),
                "perde": karakter.get("perde", "+0Hz"),
                "klon_yolu": klon_yolu,
            }

            # XTTS: ses_id dosya yolu değilse, klon_yolu'nu kullan
            if motor_adi == "xtts_v2" and klon_yolu and os.path.isfile(klon_yolu):
                ses_id = klon_yolu''',
        "karakter_icin_motor_ve_ses'e klon_yolu desteği eklendi",
    )
    if ok:
        basarili += 1

    # 3b: import os kontrolü (zaten var mı?)
    toplam += 1
    with open("core/tts_manager.py", "r", encoding="utf-8") as f:
        tts_icerik = f.read()
    if "import os" in tts_icerik:
        print("  ⏭️  import os zaten mevcut")
        basarili += 1
    else:
        ok = patch_dosya(
            "core/tts_manager.py",
            "import asyncio\nimport logging",
            "import asyncio\nimport logging\nimport os",
            "import os eklendi",
        )
        if ok:
            basarili += 1

    # ─────────────────────────────────────────────────────
    # SONUÇ
    # ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if basarili == toplam:
        print(f"✅ Tüm patchler başarılı! ({basarili}/{toplam})")
        print("\nTest için:")
        print("  python main.py --debug")
        print("  → SRT yükle → Video yükle → Klonla → Başlat")
    else:
        print(f"⚠️  {basarili}/{toplam} patch uygulandı.")
        print("Hataları kontrol edin ve gerekirse manuel düzeltin.")
        print("Yedek dosyalar: *.bak_HHMMSS")
    print("=" * 60)


if __name__ == "__main__":
    main()
