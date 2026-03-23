# -*- coding: utf-8 -*-
"""
DubSync Pro — GPU Desteği Patch (RTX 5050 / Blackwell sm_120)

PyTorch nightly cu128 kurulumundan SONRA çalıştırın.
sm_120 engelini kaldırır, gerçek CUDA testi ekler.

Kullanım:
    1. Önce PyTorch nightly kur:
       pip uninstall torch torchaudio -y
       pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128

    2. Sonra bu patch'i çalıştır:
       python patch_gpu_support.py
"""

import os
import sys
import shutil
from datetime import datetime


def patch_dosya(dosya_yolu: str, eski: str, yeni: str, aciklama: str) -> bool:
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
    if not os.path.isdir("core") or not os.path.isdir("engines"):
        print("❌ Bu scripti proje kök dizininde çalıştırın!")
        sys.exit(1)

    print("=" * 60)
    print("DubSync Pro — GPU Desteği Patch (RTX 5050 / sm_120)")
    print("=" * 60)
    basarili = 0
    toplam = 0

    # ─────────────────────────────────────────────────────
    # PATCH 1: engines/xtts_engine.py — gpu_mevcut()
    # sm_120 engelini kaldır, gerçek CUDA testi yap
    # ─────────────────────────────────────────────────────
    print("\n📁 engines/xtts_engine.py")

    toplam += 1
    ok = patch_dosya(
        "engines/xtts_engine.py",
        # ESKİ — sm_120 engelleyen kod
        '''    @staticmethod
    def gpu_mevcut() -> bool:
        """CUDA GPU mevcut ve uyumlu mu kontrol eder (sm_120 hariç)."""
        try:
            import torch
            if not torch.cuda.is_available():
                return False
            # Blackwell (sm_120) kontrolü — stable PyTorch desteklemiyor
            props = torch.cuda.get_device_properties(0)
            if hasattr(props, "major") and props.major >= 12:
                logger.warning(
                    "Blackwell GPU (sm_%d%d0) tespit edildi. "
                    "PyTorch stable henüz desteklemiyor, CPU kullanılacak.",
                    props.major, props.minor,
                )
                return False
            return True
        except (ImportError, OSError):
            return False
        except Exception:
            return False''',
        # YENİ — gerçek CUDA testi (sm_120 dahil)
        '''    @staticmethod
    def gpu_mevcut() -> bool:
        """CUDA GPU mevcut ve çalışır durumda mı kontrol eder."""
        try:
            import torch
            if not torch.cuda.is_available():
                return False

            # Gerçek CUDA testi — küçük tensor işlemi
            props = torch.cuda.get_device_properties(0)
            cap = f"sm_{props.major}{props.minor}0" if hasattr(props, "major") else "?"

            try:
                t = torch.zeros(1, device="cuda")
                del t
                logger.info(
                    "GPU kullanılabilir: %s (%s)",
                    torch.cuda.get_device_name(0), cap,
                )
                return True
            except RuntimeError as e:
                # "no kernel image" = PyTorch bu GPU'yu desteklemiyor
                logger.warning(
                    "GPU tespit edildi (%s, %s) ama CUDA çalışmıyor: %s. "
                    "CPU kullanılacak. Çözüm: PyTorch nightly cu128 kurun.",
                    torch.cuda.get_device_name(0), cap, str(e)[:100],
                )
                return False

        except (ImportError, OSError):
            return False
        except Exception:
            return False''',
        "gpu_mevcut() — sm_120 engeli kaldırıldı, gerçek CUDA testi eklendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # PATCH 2: engines/xtts_engine.py — baslat() docstring
    # "Blackwell desteklemiyor" notunu güncelle
    # ─────────────────────────────────────────────────────
    toplam += 1
    ok = patch_dosya(
        "engines/xtts_engine.py",
        '''        İlk çalıştırmada model otomatik indirilir (~1.8GB).
        GPU uyumluysa CUDA'ya taşınır, yoksa CPU'da çalışır.
        Blackwell (sm_120) GPU'lar henüz desteklenmediği için
        otomatik olarak CPU moduna düşer.''',
        '''        İlk çalıştırmada model otomatik indirilir (~1.8GB).
        GPU uyumluysa CUDA'ya taşınır, yoksa CPU'da çalışır.
        GPU testi başarısız olursa otomatik olarak CPU moduna düşer.''',
        "baslat() docstring güncellendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # PATCH 3: engines/xtts_engine.py — baslat() cihaz seçimi
    # "sm_120 otomatik CPU'ya düşer" yorumunu güncelle
    # ─────────────────────────────────────────────────────
    toplam += 1
    ok = patch_dosya(
        "engines/xtts_engine.py",
        '''        # Cihaz seçimi — sm_120 (Blackwell) otomatik CPU'ya düşer''',
        '''        # Cihaz seçimi — GPU testi başarısızsa CPU'ya düşer''',
        "baslat() yorum güncellendi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # PATCH 4: main.py — GPU kontrol bölümü
    # sm_120 uyarısını güncelle
    # ─────────────────────────────────────────────────────
    print("\n📁 main.py")

    toplam += 1
    ok = patch_dosya(
        "main.py",
        '''            # sm_120 uyarısı (Blackwell)
            if hasattr(props, "major") and props.major >= 12:
                pencere.log(
                    "  ⚠️ Blackwell GPU (sm_120): PyTorch stable henüz desteklemiyor. "
                    "XTTS CPU modunda çalışacak.",
                    "warning",
                )''',
        '''            # Blackwell GPU bilgi notu
            if hasattr(props, "major") and props.major >= 12:
                # Gerçek CUDA testi
                try:
                    _t = torch.zeros(1, device="cuda")
                    del _t
                    pencere.log(
                        f"  ✅ Blackwell GPU ({cap}): CUDA çalışıyor! "
                        "GPU modunda hızlı çalışacak.",
                        "success",
                    )
                except RuntimeError:
                    pencere.log(
                        f"  ⚠️ Blackwell GPU ({cap}): CUDA kernel bulunamadı. "
                        "CPU moduna düşecek. Çözüm: "
                        "pip install --pre torch torchaudio "
                        "--index-url https://download.pytorch.org/whl/nightly/cu128",
                        "warning",
                    )''',
        "main.py GPU kontrol — Blackwell gerçek CUDA testi",
    )
    if ok:
        basarili += 1

    # ─────────────────────────────────────────────────────
    # SONUÇ
    # ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if basarili == toplam:
        print(f"✅ Tüm patchler başarılı! ({basarili}/{toplam})")
        print()
        print("ŞİMDİ PyTorch nightly kur:")
        print("  pip uninstall torch torchaudio -y")
        print("  pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128")
        print()
        print("Sonra test et:")
        print("  python -c \"import torch; print(torch.cuda.is_available(), torch.zeros(1,device='cuda'))\"")
        print("  python main.py --debug")
    else:
        print(f"⚠️  {basarili}/{toplam} patch uygulandı.")
        print("Yedek dosyalar: *.bak_HHMMSS")
    print("=" * 60)


if __name__ == "__main__":
    main()
