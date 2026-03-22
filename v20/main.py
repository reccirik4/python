# -*- coding: utf-8 -*-
"""
DubSync Pro v1.0 — Film Altyazı Seslendirme Aracı

Ana giriş noktası. Uygulamayı başlatır:
1. Logging yapılandırması
2. ConfigManager yükleme
3. PyQt6 QApplication oluşturma
4. Ana pencere gösterme

Kullanım:
    python main.py
    python main.py --ayar /yol/dubsync_pro_settings.json
    python main.py --debug
"""

import sys
import os
import argparse
import logging
from pathlib import Path


def uygulama_dizini() -> Path:
    """
    Uygulamanın çalıştığı dizini döndürür.

    PyInstaller --onefile modunda EXE'nin bulunduğu klasörü döndürür.
    Normal Python'da main.py'nin bulunduğu klasörü döndürür.
    Settings dosyası, log klasörü vb. buraya yazılır/okunur.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller ile paketlenmiş — EXE'nin bulunduğu klasör
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def kaynak_dizini() -> Path:
    """
    Bundled kaynakların (modüller vb.) bulunduğu dizin.

    PyInstaller --onefile modunda _MEIPASS temp klasörünü döndürür.
    Normal Python'da main.py'nin bulunduğu klasörü döndürür.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def logging_yapilandir(debug: bool = False) -> None:
    """
    Logging yapılandırmasını ayarlar.

    Konsol + dosya çıkışı. Debug modunda daha detaylı log.
    """
    seviye = logging.DEBUG if debug else logging.INFO

    # Log formatı
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)-25s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Kök logger
    kok = logging.getLogger()
    kok.setLevel(seviye)

    # Mevcut handler'ları temizle (tekrar çağrılırsa)
    kok.handlers.clear()

    # Konsol handler
    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(seviye)
    konsol.setFormatter(fmt)
    kok.addHandler(konsol)

    # Dosya handler (opsiyonel)
    log_dizin = uygulama_dizini() / "logs"
    try:
        log_dizin.mkdir(exist_ok=True)
        dosya_handler = logging.FileHandler(
            log_dizin / "dubsync_pro.log",
            encoding="utf-8",
            mode="a",
        )
        dosya_handler.setLevel(logging.DEBUG)
        dosya_handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)-7s] %(name)-25s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        kok.addHandler(dosya_handler)
    except OSError:
        pass  # Log dosyası yazılamazsa sessizce devam et

    # Üçüncü parti kütüphanelerin log gürültüsünü azalt
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def argumanlari_ayristir() -> argparse.Namespace:
    """Komut satırı argümanlarını ayrıştırır."""
    parser = argparse.ArgumentParser(
        prog="DubSync Pro",
        description="Film altyazı seslendirme aracı.",
    )
    parser.add_argument(
        "--ayar",
        type=str,
        default=None,
        help="Ayar dosyası yolu (varsayılan: dubsync_pro_settings.json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug modunu etkinleştir (detaylı log).",
    )
    return parser.parse_args()


def main() -> int:
    """
    Ana uygulama fonksiyonu.

    Returns:
        Çıkış kodu (0 = başarılı).
    """
    # Argümanlar
    args = argumanlari_ayristir()

    # Logging
    logging_yapilandir(debug=args.debug)
    logger = logging.getLogger("DubSync.Main")
    logger.info("=" * 60)
    logger.info("DubSync Pro v1.0 başlatılıyor...")
    logger.info("Python: %s", sys.version.split()[0])
    logger.info("Çalışma dizini: %s", uygulama_dizini())
    if getattr(sys, "frozen", False):
        logger.info("Mod: PyInstaller EXE (frozen)")
        logger.info("Kaynak dizini: %s", kaynak_dizini())
    else:
        logger.info("Mod: Python script")
    logger.info("=" * 60)

    # ConfigManager
    if args.ayar:
        ayar_yolu = args.ayar
    else:
        ayar_yolu = str(uygulama_dizini() / "dubsync_pro_settings.json")

    try:
        from core.config_manager import ConfigManager
        config = ConfigManager(ayar_yolu)
        logger.info("Ayarlar yüklendi: %s", ayar_yolu)
    except Exception as e:
        logger.error("Ayar dosyası yüklenemedi: %s", e)
        print(f"HATA: Ayar dosyası yüklenemedi: {e}")
        return 1

    # PyQt6 kontrolü
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
    except ImportError:
        logger.error("PyQt6 yüklü değil!")
        print(
            "HATA: PyQt6 yüklü değil.\n"
            "Kurulum: pip install PyQt6\n"
            "Detaylar için requirements.txt dosyasına bakın."
        )
        return 1

    # QApplication oluştur
    app = QApplication(sys.argv)
    app.setApplicationName("DubSync Pro")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("DubSync")

    # Yüksek DPI desteği (Windows 11 ölçekleme)
    app.setStyle("Fusion")

    # Ana pencere
    try:
        from gui.main_window import MainWindow
        pencere = MainWindow(config)
        pencere.show()

        logger.info("Ana pencere gösterildi. Uygulama hazır.")
        pencere.log("DubSync Pro v1.0 başlatıldı.", "success")
        pencere.log(f"Ayarlar: {os.path.basename(ayar_yolu)}")

        # Bağımlılık kontrolü
        _bagimliliklari_kontrol_et(pencere)

    except Exception as e:
        logger.critical("Ana pencere oluşturulamadı: %s", e, exc_info=True)
        print(f"KRİTİK HATA: {e}")
        return 1

    # Uygulama döngüsü
    try:
        cikis_kodu = app.exec()
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu (Ctrl+C).")
        cikis_kodu = 0
    except Exception as e:
        logger.critical("Beklenmeyen hata: %s", e, exc_info=True)
        cikis_kodu = 1

    logger.info("DubSync Pro kapatıldı. Çıkış kodu: %d", cikis_kodu)
    return cikis_kodu


def _bagimliliklari_kontrol_et(pencere) -> None:
    """Gerekli bağımlılıkları kontrol eder ve sonuçları log'a yazar."""
    logger = logging.getLogger("DubSync.Main")

    kontroller = {
        "edge-tts": ("edge_tts", "Ücretsiz TTS motoru"),
        "numpy": ("numpy", "Ses işleme"),
        "soundfile": ("soundfile", "WAV okuma/yazma"),
        "librosa": ("librosa", "Ses analiz / time stretch"),
        "pydub": ("pydub", "Ses format dönüşüm"),
        "pysrt": ("pysrt", "SRT dosya işleme"),
    }

    eksikler = []
    for paket_adi, (modul_adi, aciklama) in kontroller.items():
        try:
            __import__(modul_adi)
            pencere.log(f"  ✅ {paket_adi} — {aciklama}")
        except ImportError:
            eksikler.append(paket_adi)
            pencere.log(f"  ❌ {paket_adi} — {aciklama} (eksik!)", "warning")

    # FFmpeg kontrolü
    import shutil
    if shutil.which("ffmpeg"):
        pencere.log("  ✅ FFmpeg — Video/ses işleme")
    else:
        eksikler.append("ffmpeg")
        pencere.log("  ❌ FFmpeg — Video/ses işleme (eksik!)", "warning")

    # Opsiyonel kontroller (DLL/import hataları uygulamayı çökertmesin)
    opsiyonel = {
        "pyrubberband": ("pyrubberband", "Kaliteli time stretch"),
        "openai": ("openai", "OpenAI TTS API"),
        "elevenlabs": ("elevenlabs", "ElevenLabs TTS API"),
    }
    for paket_adi, (modul_adi, aciklama) in opsiyonel.items():
        try:
            __import__(modul_adi)
            pencere.log(f"  ✅ {paket_adi} — {aciklama} (opsiyonel)")
        except ImportError:
            pencere.log(f"  ⬜ {paket_adi} — {aciklama} (yüklü değil)", "info")
        except Exception as e:
            pencere.log(f"  ⚠️ {paket_adi} — yükleme hatası: {e}", "warning")

    # TTS (coqui) — ayrı kontrol (torch bağımlılığı DLL crash yapabilir)
    try:
        __import__("TTS")
        pencere.log("  ✅ TTS (coqui) — XTTS-v2 lokal klonlama (opsiyonel)")
    except ImportError:
        pencere.log("  ⬜ TTS (coqui) — XTTS-v2 (yüklü değil)", "info")
        pencere.log("     Kurulum: pip install coqui-tts>=0.27.0", "info")
    except OSError as e:
        pencere.log(f"  ⚠️ TTS (coqui) — DLL hatası: {e}", "warning")
        pencere.log(
            "     Çözüm: pip uninstall torch torchaudio -y && "
            "pip install torch torchaudio --index-url "
            "https://download.pytorch.org/whl/cpu",
            "warning",
        )
    except Exception as e:
        pencere.log(f"  ⚠️ TTS (coqui) — hata: {e}", "warning")

    # GPU kontrolü (torch DLL hatası uygulamayı çökertmesin)
    try:
        import torch
        torch_versiyon = torch.__version__
        cuda_mevcut = torch.cuda.is_available()

        if cuda_mevcut:
            gpu_adi = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            vram_bytes = getattr(props, "total_memory", 0) or getattr(props, "total_mem", 0)
            cap = f"sm_{props.major}{props.minor}0" if hasattr(props, "major") else ""

            if vram_bytes > 0:
                vram = vram_bytes / (1024**3)
                pencere.log(
                    f"  🎮 GPU: {gpu_adi} ({vram:.1f} GB, {cap}) — torch {torch_versiyon}",
                    "success",
                )
            else:
                pencere.log(f"  🎮 GPU: {gpu_adi} ({cap}) — torch {torch_versiyon}", "success")

            # sm_120 uyarısı (Blackwell)
            if hasattr(props, "major") and props.major >= 12:
                pencere.log(
                    "  ⚠️ Blackwell GPU (sm_120): PyTorch stable henüz desteklemiyor. "
                    "XTTS CPU modunda çalışacak.",
                    "warning",
                )
        else:
            pencere.log(f"  ⬜ GPU: CUDA mevcut değil — torch {torch_versiyon} (CPU kullanılacak)")
    except ImportError:
        pencere.log("  ⬜ GPU: PyTorch yüklü değil (CPU kullanılacak)")
    except OSError:
        pencere.log("  ⚠️ GPU: torch DLL hatası (CPU kullanılacak)", "warning")
    except Exception as e:
        pencere.log(f"  ⬜ GPU: Kontrol hatası ({e})")

    # Sonuç
    if eksikler:
        pencere.log(
            f"⚠️ {len(eksikler)} zorunlu bağımlılık eksik: {', '.join(eksikler)}",
            "error",
        )
        pencere.log(
            "Kurulum: pip install -r requirements.txt",
            "warning",
        )
    else:
        pencere.log("✅ Tüm zorunlu bağımlılıklar mevcut.", "success")


if __name__ == "__main__":
    sys.exit(main())
