# -*- coding: utf-8 -*-
"""
DubSync Pro — XTTS Aktif Kalıcılık Patch
settings_panel.py'de config_yukle sırasında sinyalleri bastırır.

Kullanım:
    python patch_settings_yukle.py

Sorun: config_yukle sırasında her checkbox değiştiğinde
       _degisiklik → ayarlar_degisti → config_e_kaydet çağrılıyor.
       XTTS checkbox henüz set edilmeden config'e "aktif: false" yazılıyor.

Çözüm: _yukleniyor flag'i ile config_yukle sırasında sinyalleri bastır.
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

    yedek = dosya_yolu + f".bak_{datetime.now().strftime('%H%M%S')}"
    shutil.copy2(dosya_yolu, yedek)

    icerik = icerik.replace(eski, yeni, 1)

    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write(icerik)

    print(f"  ✅ {aciklama}")
    return True


def main():
    if not os.path.isdir("core") or not os.path.isdir("gui"):
        print("❌ Bu scripti proje kök dizininde çalıştırın!")
        sys.exit(1)

    print("=" * 60)
    print("DubSync Pro — XTTS Aktif Kalıcılık Patch")
    print("=" * 60)
    basarili = 0
    toplam = 0

    dosya = "gui/settings_panel.py"
    print(f"\n📁 {dosya}")

    # ── PATCH 1: __init__'e _yukleniyor flag'i ekle ──
    toplam += 1
    ok = patch_dosya(
        dosya,
        '''        self._config: Optional[ConfigManager] = None
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._olustur()''',
        '''        self._config: Optional[ConfigManager] = None
        self._yukleniyor: bool = False
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._olustur()''',
        "__init__'e _yukleniyor flag'i eklendi",
    )
    if ok:
        basarili += 1

    # ── PATCH 2: config_yukle başına/sonuna flag ekle ──
    toplam += 1
    ok = patch_dosya(
        dosya,
        '''    def config_yukle(self, config: ConfigManager):
        """Config'den tüm ayarları widget'lara yükler."""
        self._config = config''',
        '''    def config_yukle(self, config: ConfigManager):
        """Config'den tüm ayarları widget'lara yükler."""
        self._yukleniyor = True
        self._config = config''',
        "config_yukle başına _yukleniyor = True eklendi",
    )
    if ok:
        basarili += 1

    # config_yukle sonuna flag kapat (logger.info satırından önce)
    toplam += 1
    ok = patch_dosya(
        dosya,
        '''        logger.info("Ayarlar config'den yüklendi.")

    def config_e_kaydet''',
        '''        self._yukleniyor = False
        logger.info("Ayarlar config'den yüklendi.")

    def config_e_kaydet''',
        "config_yukle sonuna _yukleniyor = False eklendi",
    )
    if ok:
        basarili += 1

    # ── PATCH 3: _degisiklik fonksiyonuna guard ekle ──
    toplam += 1
    ok = patch_dosya(
        dosya,
        '''    def _degisiklik(self):
        """Herhangi bir ayar değiştiğinde sinyal gönderir."""''',
        '''    def _degisiklik(self):
        """Herhangi bir ayar değiştiğinde sinyal gönderir."""
        if self._yukleniyor:
            return''',
        "_degisiklik'e _yukleniyor guard eklendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # SONUÇ
    # ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if basarili == toplam:
        print(f"✅ Tüm patchler başarılı! ({basarili}/{toplam})")
        print("\nArtık XTTS aktif işareti kalıcı olacak.")
        print("Test: python main.py --debug")
    else:
        print(f"⚠️  {basarili}/{toplam} patch uygulandı.")
        print("Yedek dosyalar: *.bak_HHMMSS")
    print("=" * 60)


if __name__ == "__main__":
    main()
