# -*- coding: utf-8 -*-
"""
DubSync Pro — Zaman Ayarlayıcı (time_stretcher.py)

Ses dosyalarını pitch değiştirmeden hızlandırır veya yavaşlatır.
İki motor destekler:
  1. librosa (varsayılan, saf Python, her yerde çalışır)
  2. pyrubberband (opsiyonel, daha kaliteli, rubberband CLI gerektirir)

Otomatik mod: rubberband varsa onu kullanır, yoksa librosa'ya düşer.
"""

import logging
import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger("DubSync.TimeStretcher")


# ============================================================
# Motor Seçimi
# ============================================================

class StretchMotor(Enum):
    """Time stretch motoru."""
    OTOMATIK = "otomatik"
    LIBROSA = "librosa"
    RUBBERBAND = "rubberband"


# ============================================================
# Motor Kullanılabilirlik Kontrolü
# ============================================================

def _rubberband_mevcut() -> bool:
    """rubberband CLI'nin PATH'te olup olmadığını kontrol eder."""
    return shutil.which("rubberband") is not None


def _pyrubberband_mevcut() -> bool:
    """pyrubberband Python paketinin yüklü olup olmadığını kontrol eder."""
    try:
        import pyrubberband  # noqa: F401
        return True
    except ImportError:
        return False


def kullanilabilir_motorlar() -> dict[str, bool]:
    """
    Hangi time stretch motorlarının kullanılabilir olduğunu döndürür.

    Returns:
        {"librosa": True/False, "rubberband": True/False}
    """
    rb_ok = _rubberband_mevcut() and _pyrubberband_mevcut()

    try:
        import librosa  # noqa: F401
        librosa_ok = True
    except ImportError:
        librosa_ok = False

    return {
        "librosa": librosa_ok,
        "rubberband": rb_ok,
    }


def en_iyi_motor() -> StretchMotor:
    """Mevcut ortam için en iyi motoru döndürür."""
    motorlar = kullanilabilir_motorlar()
    if motorlar["rubberband"]:
        return StretchMotor.RUBBERBAND
    if motorlar["librosa"]:
        return StretchMotor.LIBROSA
    raise RuntimeError(
        "Hiçbir time stretch motoru kullanılamıyor. "
        "librosa veya pyrubberband+rubberband-cli kurun."
    )


# ============================================================
# Ana Sınıf
# ============================================================

class TimeStretcher:
    """
    Ses dosyalarını pitch koruyarak hızlandırır/yavaşlatır.

    Kullanım:
        stretcher = TimeStretcher(motor="otomatik")
        stretcher.hizlandir("girdi.wav", "cikti.wav", oran=1.5)
        stretcher.sureyegore("girdi.wav", "cikti.wav", hedef_ms=2000)
    """

    def __init__(
        self,
        motor: str = "otomatik",
        hedef_sr: int = 48000,
    ):
        """
        Args:
            motor: "otomatik", "librosa" veya "rubberband".
            hedef_sr: Çıkış örnekleme hızı (Hz).
        """
        self._hedef_sr = hedef_sr

        if motor == "otomatik":
            self._motor = en_iyi_motor()
        else:
            self._motor = StretchMotor(motor)

        # Motor gerçekten kullanılabilir mi kontrol et
        motorlar = kullanilabilir_motorlar()
        if self._motor == StretchMotor.RUBBERBAND and not motorlar["rubberband"]:
            logger.warning(
                "Rubberband kullanılamıyor, librosa'ya düşülüyor."
            )
            self._motor = StretchMotor.LIBROSA

        if self._motor == StretchMotor.LIBROSA and not motorlar["librosa"]:
            raise RuntimeError("librosa yüklü değil: pip install librosa")

        logger.info("TimeStretcher başlatıldı: motor=%s, sr=%d", self._motor.value, hedef_sr)

    @classmethod
    def ayarlardan_olustur(cls, config) -> "TimeStretcher":
        """ConfigManager'dan ayarlarla oluşturur."""
        return cls(
            motor=config.al("zamanlama.time_stretch_motoru", "otomatik"),
            hedef_sr=config.al("ses.ornekleme_hizi", 48000),
        )

    # --------------------------------------------------------
    # Ana İşlemler
    # --------------------------------------------------------

    def hizlandir(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        oran: float,
    ) -> bool:
        """
        Ses dosyasını belirtilen oranla hızlandırır veya yavaşlatır.

        Args:
            girdi_yolu: Kaynak ses dosyası (.wav).
            cikti_yolu: Çıkış ses dosyası (.wav).
            oran: Hız oranı.
                  >1.0 = hızlandır (2.0 = 2x hızlı, yarı süre)
                  <1.0 = yavaşlat (0.5 = yarı hız, 2x süre)
                  1.0  = değişiklik yok.

        Returns:
            True: başarılı, False: başarısız.
        """
        if not os.path.isfile(girdi_yolu):
            logger.error("Girdi dosyası bulunamadı: %s", girdi_yolu)
            return False

        # 1.0 ise kopyala
        if abs(oran - 1.0) < 0.01:
            Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(girdi_yolu, cikti_yolu)
            return True

        # Oran sınırları (güvenlik)
        oran = max(0.25, min(4.0, oran))

        try:
            if self._motor == StretchMotor.RUBBERBAND:
                return self._stretch_rubberband(girdi_yolu, cikti_yolu, oran)
            else:
                return self._stretch_librosa(girdi_yolu, cikti_yolu, oran)
        except Exception as e:
            logger.error("Time stretch hatası: %s", e)
            # Fallback: diğer motoru dene
            if self._motor == StretchMotor.RUBBERBAND:
                logger.info("Rubberband başarısız, librosa deneniyor...")
                try:
                    return self._stretch_librosa(girdi_yolu, cikti_yolu, oran)
                except Exception as e2:
                    logger.error("Librosa fallback de başarısız: %s", e2)
            return False

    def sureyegore(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        hedef_ms: int,
    ) -> bool:
        """
        Ses dosyasını hedef süreye göre uzatır/kısaltır.

        Args:
            girdi_yolu: Kaynak ses dosyası.
            cikti_yolu: Çıkış ses dosyası.
            hedef_ms: Hedef süre (milisaniye).

        Returns:
            True: başarılı, False: başarısız.
        """
        if hedef_ms <= 0:
            logger.error("Hedef süre geçersiz: %d ms", hedef_ms)
            return False

        # Girdi süresini hesapla
        girdi_ms = self.sure_hesapla(girdi_yolu)
        if girdi_ms <= 0:
            logger.error("Girdi süresi hesaplanamadı: %s", girdi_yolu)
            return False

        oran = girdi_ms / hedef_ms
        logger.debug(
            "Süreye göre stretch: girdi=%dms, hedef=%dms, oran=%.3f",
            girdi_ms, hedef_ms, oran,
        )
        return self.hizlandir(girdi_yolu, cikti_yolu, oran)

    # --------------------------------------------------------
    # Librosa ile Time Stretch
    # --------------------------------------------------------

    def _stretch_librosa(
        self, girdi_yolu: str, cikti_yolu: str, oran: float
    ) -> bool:
        """
        librosa.effects.time_stretch ile hız ayarı yapar.

        librosa'da oran >1 = hızlı çalma (kısaltma), bu yüzden
        direkt oran değerini geçiyoruz.
        """
        import librosa

        # Dosyayı oku (hedef sr ile)
        y, sr = librosa.load(girdi_yolu, sr=self._hedef_sr, mono=True)

        # Time stretch uygula
        # librosa rate>1 = daha hızlı (süre kısalır)
        y_stretched = librosa.effects.time_stretch(y, rate=oran)

        # Çıkış dizinini oluştur
        Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)

        # WAV olarak kaydet (24-bit)
        sf.write(cikti_yolu, y_stretched, self._hedef_sr, subtype="PCM_24")

        logger.debug(
            "librosa stretch: oran=%.2f, girdi=%d örnek, çıkış=%d örnek",
            oran, len(y), len(y_stretched),
        )
        return True

    # --------------------------------------------------------
    # Rubberband ile Time Stretch (Yüksek Kalite)
    # --------------------------------------------------------

    def _stretch_rubberband(
        self, girdi_yolu: str, cikti_yolu: str, oran: float
    ) -> bool:
        """
        pyrubberband ile hız ayarı yapar.

        Rubberband, librosa'dan önemli ölçüde daha kaliteli sonuç verir,
        özellikle konuşma seslerinde.
        """
        import pyrubberband as pyrb

        # Dosyayı oku
        y, sr = sf.read(girdi_yolu, dtype="float64")

        # Mono'ya çevir (gerekirse)
        if y.ndim > 1:
            y = np.mean(y, axis=1)

        # Resample (hedef sr farklıysa)
        if sr != self._hedef_sr:
            import librosa
            y = librosa.resample(y, orig_sr=sr, target_sr=self._hedef_sr)
            sr = self._hedef_sr

        # Rubberband time stretch
        # pyrubberband'de rate>1 = daha hızlı çalma
        y_stretched = pyrb.time_stretch(y, sr, oran)

        # Çıkış dizinini oluştur
        Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)

        # WAV olarak kaydet (24-bit)
        sf.write(cikti_yolu, y_stretched, self._hedef_sr, subtype="PCM_24")

        logger.debug(
            "rubberband stretch: oran=%.2f, girdi=%d örnek, çıkış=%d örnek",
            oran, len(y), len(y_stretched),
        )
        return True

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @staticmethod
    def sure_hesapla(dosya_yolu: str) -> int:
        """
        Ses dosyasının süresini milisaniye olarak hesaplar.

        Args:
            dosya_yolu: Ses dosya yolu.

        Returns:
            Süre (ms). Hata durumunda 0.
        """
        try:
            bilgi = sf.info(dosya_yolu)
            return int(bilgi.duration * 1000)
        except Exception as e:
            logger.warning("Süre hesaplanamadı (%s): %s", dosya_yolu, e)
            return 0

    def sessizlik_ekle(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        basa_ms: int = 0,
        sona_ms: int = 0,
    ) -> bool:
        """
        Ses dosyasının başına ve/veya sonuna sessizlik ekler.

        Args:
            girdi_yolu: Kaynak ses dosyası.
            cikti_yolu: Çıkış ses dosyası.
            basa_ms: Başa eklenecek sessizlik (ms).
            sona_ms: Sona eklenecek sessizlik (ms).

        Returns:
            True: başarılı.
        """
        try:
            y, sr = sf.read(girdi_yolu, dtype="float64")
            if y.ndim > 1:
                y = np.mean(y, axis=1)

            parcalar = []

            if basa_ms > 0:
                bas_ornek = int(sr * basa_ms / 1000)
                parcalar.append(np.zeros(bas_ornek, dtype=np.float64))

            parcalar.append(y)

            if sona_ms > 0:
                son_ornek = int(sr * sona_ms / 1000)
                parcalar.append(np.zeros(son_ornek, dtype=np.float64))

            birlesik = np.concatenate(parcalar)

            Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)
            sf.write(cikti_yolu, birlesik, sr, subtype="PCM_24")

            logger.debug(
                "Sessizlik eklendi: başa=%dms, sona=%dms", basa_ms, sona_ms
            )
            return True

        except Exception as e:
            logger.error("Sessizlik ekleme hatası: %s", e)
            return False

    def fade_uygula(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        fade_in_ms: int = 30,
        fade_out_ms: int = 30,
    ) -> bool:
        """
        Ses dosyasına fade-in ve fade-out uygular.

        Args:
            girdi_yolu: Kaynak ses dosyası.
            cikti_yolu: Çıkış ses dosyası.
            fade_in_ms: Fade-in süresi (ms).
            fade_out_ms: Fade-out süresi (ms).

        Returns:
            True: başarılı.
        """
        try:
            y, sr = sf.read(girdi_yolu, dtype="float64")
            if y.ndim > 1:
                y = np.mean(y, axis=1)

            toplam_ornek = len(y)

            # Fade-in
            if fade_in_ms > 0:
                fade_in_ornek = min(int(sr * fade_in_ms / 1000), toplam_ornek)
                fade_in_curve = np.linspace(0.0, 1.0, fade_in_ornek)
                y[:fade_in_ornek] *= fade_in_curve

            # Fade-out
            if fade_out_ms > 0:
                fade_out_ornek = min(int(sr * fade_out_ms / 1000), toplam_ornek)
                fade_out_curve = np.linspace(1.0, 0.0, fade_out_ornek)
                y[-fade_out_ornek:] *= fade_out_curve

            Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)
            sf.write(cikti_yolu, y, sr, subtype="PCM_24")

            logger.debug(
                "Fade uygulandı: in=%dms, out=%dms", fade_in_ms, fade_out_ms
            )
            return True

        except Exception as e:
            logger.error("Fade uygulama hatası: %s", e)
            return False

    def kirp(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        hedef_ms: int,
    ) -> bool:
        """
        Ses dosyasını belirtilen süreye kırpar (sondan keser).

        Taşma durumunda hızlandırma yerine kırpma tercih edildiğinde kullanılır.

        Args:
            girdi_yolu: Kaynak ses dosyası.
            cikti_yolu: Çıkış ses dosyası.
            hedef_ms: Hedef süre (ms). Sesin bu kadarı korunur.

        Returns:
            True: başarılı.
        """
        try:
            y, sr = sf.read(girdi_yolu, dtype="float64")
            if y.ndim > 1:
                y = np.mean(y, axis=1)

            hedef_ornek = int(sr * hedef_ms / 1000)
            if hedef_ornek < len(y):
                y = y[:hedef_ornek]

            Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)
            sf.write(cikti_yolu, y, sr, subtype="PCM_24")

            logger.debug("Kırpıldı: %dms → %d örnek", hedef_ms, hedef_ornek)
            return True

        except Exception as e:
            logger.error("Kırpma hatası: %s", e)
            return False

    # --------------------------------------------------------
    # Bilgi
    # --------------------------------------------------------

    @property
    def motor_adi(self) -> str:
        """Aktif motor adı."""
        return self._motor.value

    @property
    def hedef_sr(self) -> int:
        """Hedef örnekleme hızı."""
        return self._hedef_sr

    def __repr__(self) -> str:
        return f"<TimeStretcher motor={self._motor.value} sr={self._hedef_sr}>"
