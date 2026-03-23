# -*- coding: utf-8 -*-
"""
DubSync Pro — Debug Logger (debug_logger.py)

VS Code entegre terminalinde renkli, detaylı log çıktısı sağlar.
Harici kütüphane gerektirmez (saf ANSI escape kodları).

Özellikler:
- Renkli konsol çıktısı (DEBUG=gri, INFO=mavi, WARNING=sarı, ERROR=kırmızı, SUCCESS=yeşil)
- @izle decorator'u (sync + async fonksiyon giriş/çıkış izleme, süre ölçümü)
- Modül bazlı filtreleme
- Windows 10+ / VS Code integrated terminal tam uyumlu

Kullanım:
    from core.debug_logger import RenkliFormatter, izle, SUCCESS

    # Decorator ile fonksiyon izleme:
    @izle
    async def ses_uret(metin, ses_id):
        ...

    @izle
    def srt_oku(dosya_yolu):
        ...
"""

import logging
import time
import asyncio
import inspect
import os
import sys
from functools import wraps
from typing import Optional


# ============================================================
# Windows ANSI Desteği
# ============================================================

def _windows_ansi_etkinlestir():
    """
    Windows 10+ konsolunda ANSI escape kodlarını etkinleştirir.
    VS Code integrated terminal zaten destekler, ama cmd.exe için gerekli.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass  # Hata olursa sessizce devam et (VS Code zaten destekler)

_windows_ansi_etkinlestir()


# ============================================================
# Özel Log Seviyesi: SUCCESS
# ============================================================

SUCCESS = 25  # INFO(20) ile WARNING(30) arası
logging.addLevelName(SUCCESS, "SUCCESS")


def success(self, mesaj, *args, **kwargs):
    """Logger'a success metodu ekler."""
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, mesaj, args, **kwargs)

logging.Logger.success = success


# ============================================================
# ANSI Renk Kodları
# ============================================================

class _Renk:
    """ANSI escape renk kodları. Harici kütüphane gerektirmez."""

    SIFIRLA  = "\033[0m"
    KALIN    = "\033[1m"
    SOLUK    = "\033[2m"
    ITALIK   = "\033[3m"

    # Ön plan (yazı) renkleri
    SIYAH    = "\033[30m"
    KIRMIZI  = "\033[31m"
    YESIL    = "\033[32m"
    SARI     = "\033[33m"
    MAVI     = "\033[34m"
    MOR      = "\033[35m"
    CYAN     = "\033[36m"
    BEYAZ    = "\033[37m"
    GRI      = "\033[90m"

    # Parlak renkler
    P_KIRMIZI = "\033[91m"
    P_YESIL   = "\033[92m"
    P_SARI    = "\033[93m"
    P_MAVI    = "\033[94m"
    P_MOR     = "\033[95m"
    P_CYAN    = "\033[96m"

    # Arka plan renkleri
    BG_KIRMIZI = "\033[41m"
    BG_YESIL   = "\033[42m"
    BG_SARI    = "\033[43m"


R = _Renk  # Kısa alias


# ============================================================
# Renkli Formatter
# ============================================================

class RenkliFormatter(logging.Formatter):
    """
    VS Code terminali için renkli log formatter.

    Her seviye farklı renkte görünür:
    - DEBUG    → Gri (soluk)
    - INFO     → Mavi
    - SUCCESS  → Yeşil (kalın)
    - WARNING  → Sarı (kalın)
    - ERROR    → Kırmızı (kalın)
    - CRITICAL → Beyaz yazı, kırmızı arka plan

    Format:
    HH:MM:SS [SEVİYE ] Modül.Adı              | Mesaj
    """

    SEVIYE_RENKLERI = {
        logging.DEBUG:    R.GRI,
        logging.INFO:     R.P_MAVI,
        SUCCESS:          R.KALIN + R.P_YESIL,
        logging.WARNING:  R.KALIN + R.P_SARI,
        logging.ERROR:    R.KALIN + R.P_KIRMIZI,
        logging.CRITICAL: R.KALIN + R.BEYAZ + R.BG_KIRMIZI,
    }

    SEVIYE_IKONLARI = {
        logging.DEBUG:    "🔍",
        logging.INFO:     "ℹ️ ",
        SUCCESS:          "✅",
        logging.WARNING:  "⚠️ ",
        logging.ERROR:    "❌",
        logging.CRITICAL: "💀",
    }

    def __init__(self, ikon_kullan: bool = True):
        """
        Args:
            ikon_kullan: Emoji ikonları gösterilsin mi? (VS Code destekler)
        """
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)-25s | %(message)s",
            datefmt="%H:%M:%S",
        )
        self._ikon_kullan = ikon_kullan

    def format(self, record: logging.LogRecord) -> str:
        # Seviye rengini belirle
        renk = self.SEVIYE_RENKLERI.get(record.levelno, R.BEYAZ)
        ikon = self.SEVIYE_IKONLARI.get(record.levelno, "  ") if self._ikon_kullan else ""

        # Zaman — gri
        zaman = self.formatTime(record, self.datefmt)
        zaman_str = f"{R.GRI}{zaman}{R.SIFIRLA}"

        # Seviye — renkli
        seviye_adi = record.levelname
        seviye_str = f"{renk}{seviye_adi:<7s}{R.SIFIRLA}"

        # Modül adı — cyan
        modul_str = f"{R.CYAN}{record.name:<25s}{R.SIFIRLA}"

        # Mesaj — seviye renginde
        mesaj = record.getMessage()

        # Exception bilgisi varsa ekle
        if record.exc_info and record.exc_info[0] is not None:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        exc_str = ""
        if record.exc_text:
            exc_str = f"\n{R.KIRMIZI}{record.exc_text}{R.SIFIRLA}"

        # Stack info
        stack_str = ""
        if record.stack_info:
            stack_str = f"\n{R.GRI}{record.stack_info}{R.SIFIRLA}"

        return (
            f"{zaman_str} {ikon}{seviye_str} {modul_str} {R.GRI}│{R.SIFIRLA} "
            f"{renk}{mesaj}{R.SIFIRLA}{exc_str}{stack_str}"
        )


# ============================================================
# Dosya Formatter (renksiz, düz metin)
# ============================================================

class DosyaFormatter(logging.Formatter):
    """
    Log dosyası için renksiz formatter.
    Tarih + saat + seviye + modül + mesaj.
    """

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(levelname)-7s] %(name)-25s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


# ============================================================
# @izle Decorator (Sync + Async)
# ============================================================

def izle(func=None, *, seviye: int = logging.DEBUG, sonuc_goster: bool = False):
    """
    Fonksiyon giriş/çıkış izleme decorator'u.

    Hem sync hem async fonksiyonları destekler.
    Her çağrıda VS Code konsoluna şunları yazar:
    - ▶ Giriş: fonksiyon adı + parametreler
    - ✔ Çıkış: fonksiyon adı + çalışma süresi (ms)
    - ✘ Hata: fonksiyon adı + hata mesajı + süre

    Kullanım:
        @izle
        def srt_oku(dosya_yolu):
            ...

        @izle(seviye=logging.INFO)
        async def ses_uret(metin, ses_id):
            ...

        @izle(sonuc_goster=True)
        def hesapla(x, y):
            return x + y
    """

    def dekorator(fn):
        fn_logger = logging.getLogger(f"DubSync.izle.{fn.__qualname__}")

        def _param_ozet(*args, **kwargs) -> str:
            """Parametre listesini kısa özet olarak formatlar."""
            parcalar = []

            # İlk arg genellikle self — atla
            baslangic = 0
            sig = inspect.signature(fn)
            param_isimleri = list(sig.parameters.keys())
            if param_isimleri and param_isimleri[0] in ("self", "cls"):
                baslangic = 1

            for i, arg in enumerate(args[baslangic:], start=baslangic):
                if i < len(param_isimleri):
                    ad = param_isimleri[i]
                else:
                    ad = f"arg{i}"
                deger = _deger_kisalt(arg)
                parcalar.append(f"{ad}={deger}")

            for anahtar, deger in kwargs.items():
                parcalar.append(f"{anahtar}={_deger_kisalt(deger)}")

            return ", ".join(parcalar) if parcalar else ""

        def _deger_kisalt(deger, maks_uzunluk: int = 80) -> str:
            """Değeri kısa string'e çevirir (uzunsa kırpar)."""
            metin = repr(deger)
            if len(metin) > maks_uzunluk:
                return metin[:maks_uzunluk - 3] + "..."
            return metin

        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_sarmalayici(*args, **kwargs):
                param_str = _param_ozet(*args, **kwargs)
                fn_logger.log(
                    seviye,
                    "▶ %s(%s)",
                    fn.__qualname__,
                    param_str,
                )
                baslangic = time.perf_counter()
                try:
                    sonuc = await fn(*args, **kwargs)
                    sure_ms = (time.perf_counter() - baslangic) * 1000
                    if sonuc_goster:
                        fn_logger.log(
                            seviye,
                            "✔ %s → %s  [%.1f ms]",
                            fn.__qualname__,
                            _deger_kisalt(sonuc, 120),
                            sure_ms,
                        )
                    else:
                        fn_logger.log(
                            seviye,
                            "✔ %s  [%.1f ms]",
                            fn.__qualname__,
                            sure_ms,
                        )
                    return sonuc
                except Exception as e:
                    sure_ms = (time.perf_counter() - baslangic) * 1000
                    fn_logger.error(
                        "✘ %s HATA: %s  [%.1f ms]",
                        fn.__qualname__,
                        str(e)[:200],
                        sure_ms,
                    )
                    raise

            return async_sarmalayici
        else:
            @wraps(fn)
            def sync_sarmalayici(*args, **kwargs):
                param_str = _param_ozet(*args, **kwargs)
                fn_logger.log(
                    seviye,
                    "▶ %s(%s)",
                    fn.__qualname__,
                    param_str,
                )
                baslangic = time.perf_counter()
                try:
                    sonuc = fn(*args, **kwargs)
                    sure_ms = (time.perf_counter() - baslangic) * 1000
                    if sonuc_goster:
                        fn_logger.log(
                            seviye,
                            "✔ %s → %s  [%.1f ms]",
                            fn.__qualname__,
                            _deger_kisalt(sonuc, 120),
                            sure_ms,
                        )
                    else:
                        fn_logger.log(
                            seviye,
                            "✔ %s  [%.1f ms]",
                            fn.__qualname__,
                            sure_ms,
                        )
                    return sonuc
                except Exception as e:
                    sure_ms = (time.perf_counter() - baslangic) * 1000
                    fn_logger.error(
                        "✘ %s HATA: %s  [%.1f ms]",
                        fn.__qualname__,
                        str(e)[:200],
                        sure_ms,
                    )
                    raise

            return sync_sarmalayici

    # @izle veya @izle(seviye=...) her iki kullanımı destekle
    if func is not None:
        return dekorator(func)
    return dekorator


# ============================================================
# Logging Yapılandırma Fonksiyonu
# ============================================================

def logging_pipilandir(
    debug: bool = False,
    log_dizin: Optional[str] = None,
    ikon_kullan: bool = True,
) -> None:
    """
    DubSync Pro logging yapılandırmasını ayarlar.

    Renkli konsol + dosya çıkışı.

    Args:
        debug: True ise DEBUG seviyesinde, False ise INFO.
        log_dizin: Log dosya dizini. None ise otomatik.
        ikon_kullan: Emoji ikonları kullanılsın mı?
    """
    seviye = logging.DEBUG if debug else logging.INFO

    # Kök logger
    kok = logging.getLogger()
    kok.setLevel(seviye)

    # Mevcut handler'ları temizle (tekrar çağrılırsa)
    kok.handlers.clear()

    # ── Konsol Handler (renkli) ──────────────────────────────
    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(seviye)
    konsol.setFormatter(RenkliFormatter(ikon_kullan=ikon_kullan))
    kok.addHandler(konsol)

    # ── Dosya Handler (renksiz) ──────────────────────────────
    if log_dizin is None:
        # Proje kök dizinini bul
        from pathlib import Path
        if getattr(sys, "frozen", False):
            log_dizin = str(Path(sys.executable).parent / "logs")
        else:
            log_dizin = str(Path(__file__).resolve().parent.parent / "logs")

    try:
        os.makedirs(log_dizin, exist_ok=True)
        dosya_handler = logging.FileHandler(
            os.path.join(log_dizin, "dubsync_pro.log"),
            encoding="utf-8",
            mode="a",
        )
        dosya_handler.setLevel(logging.DEBUG)  # Dosyaya her şeyi yaz
        dosya_handler.setFormatter(DosyaFormatter())
        kok.addHandler(dosya_handler)
    except OSError:
        pass  # Yazılamazsa sessizce devam et

    # ── Üçüncü parti kütüphanelerin gürültüsünü azalt ──────
    for modul in (
        "urllib3", "asyncio", "httpx", "httpcore", "PIL", "matplotlib",
        "torio", "torio._extension", "numba", "numba.core",
        "numba.core.byteflow", "numba.core.interpreter",
    ):
        logging.getLogger(modul).setLevel(logging.WARNING)


# ============================================================
# Yardımcı: Hızlı Test
# ============================================================

if __name__ == "__main__":
    """Doğrudan çalıştırılırsa test çıktısı üretir."""
    logging_pipilandir(debug=True)
    logger = logging.getLogger("DubSync.Test")

    logger.debug("Bu bir DEBUG mesajı — gri renkte görünmeli")
    logger.info("Bu bir INFO mesajı — mavi renkte görünmeli")
    logger.success("Bu bir SUCCESS mesajı — yeşil renkte görünmeli")
    logger.warning("Bu bir WARNING mesajı — sarı renkte görünmeli")
    logger.error("Bu bir ERROR mesajı — kırmızı renkte görünmeli")
    logger.critical("Bu bir CRITICAL mesajı — kırmızı arka planda görünmeli")

    print()
    logger.info("=" * 50)
    logger.info("Türkçe karakter testi: Çöğüş işini böyle yapmışsın")
    logger.info("Emoji testi: 🎬🚀📋▶️⏸️")
    logger.info("=" * 50)

    # Decorator testi
    @izle
    def toplama_testi(a: int, b: int) -> int:
        return a + b

    @izle(sonuc_goster=True)
    def carpma_testi(x: int, y: int) -> int:
        return x * y

    @izle
    async def async_testi(sure: float):
        await asyncio.sleep(sure)
        return "tamamlandı"

    @izle
    def hata_testi():
        raise ValueError("Test hatası!")

    toplama_testi(3, 5)
    carpma_testi(4, 7)
    asyncio.run(async_testi(0.1))

    try:
        hata_testi()
    except ValueError:
        pass

    print()
    logger.success("Tüm testler tamamlandı! VS Code konsolunda renkleri kontrol edin.")
