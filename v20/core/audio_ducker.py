# -*- coding: utf-8 -*-
"""
DubSync Pro — Audio Ducker (audio_ducker.py)

Orijinal video sesini (müzik, efekt, ortam) TTS seslendirmesi
sırasında otomatik olarak kısar ve seslendirme bitince geri yükseltir.

İki yöntem destekler:
  1. Basit Volume Ducking: Altyazı zamanlarına göre volume envelope
  2. FFmpeg Sidechain: TTS ses kanalını tetikleyici olarak kullanır
"""

import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from core.srt_parser import AltyaziDosyasi

logger = logging.getLogger("DubSync.AudioDucker")


# ============================================================
# Ducking Sonucu
# ============================================================

class DuckingSonucu:
    """Ducking işleminin sonucunu tutar."""

    def __init__(self):
        self.basarili: bool = False
        self.dosya_yolu: str = ""
        self.yontem: str = ""
        self.sure_ms: int = 0
        self.hata_mesaji: str = ""

    def __repr__(self) -> str:
        durum = "başarılı" if self.basarili else "başarısız"
        return f"<DuckingSonucu {durum} yöntem={self.yontem}>"


# ============================================================
# Ana Sınıf
# ============================================================

class AudioDucker:
    """
    Orijinal video sesini diyalog anlarında kısar.

    Basit ducking akışı:
    1. Video'dan ses çıkar (FFmpeg).
    2. Altyazı zamanlarına göre volume envelope oluştur.
    3. Envelope'u orijinal sese uygula.
    4. TTS sesiyle miksle.
    5. Mikslenen sesi çıkış olarak kaydet.

    Sidechain ducking akışı:
    1. FFmpeg sidechaincompress filtresi ile otomatik ducking.
    2. TTS kanalı tetikleyici (sidechain input) olarak kullanılır.

    Kullanım:
        ducker = AudioDucker(duck_seviye_db=-15)
        sonuc = ducker.basit_duck(
            orijinal_ses="film_ses.wav",
            tts_ses="tts_birlesik.wav",
            dosya=altyazi_dosyasi,
            cikis_yolu="output/mikslenmis.wav",
        )
    """

    def __init__(
        self,
        duck_seviye_db: float = -15.0,
        attack_ms: int = 200,
        release_ms: int = 500,
        on_duck_ms: int = 150,
        esik_db: float = -30.0,
        sr: int = 48000,
    ):
        """
        Args:
            duck_seviye_db: Ducking sırasında ses seviyesi düşüşü (dB).
                            -15 = orijinal sesin %18'ine düşürür.
            attack_ms: Ducking başlangıç geçiş süresi (ms).
            release_ms: Ducking bitiş geçiş süresi (ms).
            on_duck_ms: Diyalogdan önce ducking başlatma süresi (ms).
            esik_db: Bu seviyenin altındaki sesler için ducking uygulanmaz.
            sr: Örnekleme hızı.
        """
        self._duck_seviye_db = duck_seviye_db
        self._attack_ms = attack_ms
        self._release_ms = release_ms
        self._on_duck_ms = on_duck_ms
        self._esik_db = esik_db
        self._sr = sr

    @classmethod
    def ayarlardan_olustur(cls, config) -> "AudioDucker":
        """ConfigManager'dan oluşturur."""
        return cls(
            duck_seviye_db=config.al("ducking.duck_seviye_db", -15.0),
            attack_ms=config.al("ducking.attack_ms", 200),
            release_ms=config.al("ducking.release_ms", 500),
            on_duck_ms=config.al("ducking.on_duck_ms", 150),
            esik_db=config.al("ducking.esik_db", -30.0),
            sr=config.al("ses.ornekleme_hizi", 48000),
        )

    # --------------------------------------------------------
    # Video'dan Ses Çıkarma
    # --------------------------------------------------------

    @staticmethod
    def videodan_ses_cikar(
        video_yolu: str,
        cikis_yolu: str,
        sr: int = 48000,
    ) -> bool:
        """
        Video dosyasından ses kanalını WAV olarak çıkarır.

        Args:
            video_yolu: Video dosya yolu.
            cikis_yolu: Çıkış WAV dosya yolu.
            sr: Hedef örnekleme hızı.

        Returns:
            True: başarılı.
        """
        if not os.path.isfile(video_yolu):
            logger.error("Video dosyası bulunamadı: %s", video_yolu)
            return False

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        try:
            sonuc = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", video_yolu,
                    "-vn",                      # Video yok
                    "-acodec", "pcm_s24le",     # 24-bit PCM
                    "-ar", str(sr),             # Örnekleme hızı
                    "-ac", "2",                 # Stereo koru
                    cikis_yolu,
                ],
                capture_output=True,
                timeout=300,
            )
            if sonuc.returncode == 0 and os.path.isfile(cikis_yolu):
                logger.info("Ses çıkarıldı: %s", cikis_yolu)
                return True

            hata = sonuc.stderr.decode(errors="replace")[:300]
            logger.error("FFmpeg ses çıkarma hatası: %s", hata)
            return False

        except FileNotFoundError:
            logger.error(
                "FFmpeg bulunamadı. Kurulum: winget install ffmpeg "
                "veya https://ffmpeg.org/download.html"
            )
            return False
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg zaman aşımı (300s).")
            return False
        except Exception as e:
            logger.error("Ses çıkarma hatası: %s", e)
            return False

    # --------------------------------------------------------
    # Yöntem 1: Basit Volume Ducking
    # --------------------------------------------------------

    def basit_duck(
        self,
        orijinal_ses: str,
        tts_ses: str,
        dosya: AltyaziDosyasi,
        cikis_yolu: str,
    ) -> DuckingSonucu:
        """
        Altyazı zamanlarına göre volume envelope ile ducking uygular.

        Akış:
        1. Orijinal sesi oku.
        2. Altyazı zamanlarına göre ducking envelope oluştur.
        3. Envelope'u orijinal sese uygula (ses kısılır).
        4. TTS sesiyle miksle (topla).
        5. Clipping önle ve kaydet.

        Args:
            orijinal_ses: Orijinal video ses dosyası (WAV).
            tts_ses: TTS birleşik ses dosyası (WAV).
            dosya: AltyaziDosyasi (zamanlama bilgisi için).
            cikis_yolu: Mikslenen çıkış dosyası.

        Returns:
            DuckingSonucu nesnesi.
        """
        sonuc = DuckingSonucu()
        sonuc.yontem = "basit"

        # Orijinal sesi oku
        orijinal = self._ses_oku(orijinal_ses)
        if orijinal is None:
            sonuc.hata_mesaji = f"Orijinal ses okunamadı: {orijinal_ses}"
            return sonuc

        # TTS sesi oku
        tts = self._ses_oku(tts_ses)
        if tts is None:
            sonuc.hata_mesaji = f"TTS ses okunamadı: {tts_ses}"
            return sonuc

        # Uzunlukları eşitle (uzun olana göre pad)
        max_uzunluk = max(len(orijinal), len(tts))
        if len(orijinal) < max_uzunluk:
            orijinal = np.pad(orijinal, (0, max_uzunluk - len(orijinal)))
        if len(tts) < max_uzunluk:
            tts = np.pad(tts, (0, max_uzunluk - len(tts)))

        # Ducking envelope oluştur
        envelope = self._envelope_olustur(max_uzunluk, dosya)

        # Envelope'u orijinal sese uygula
        orijinal_ducked = orijinal * envelope

        # TTS ile miksle
        miks = orijinal_ducked + tts

        # Clipping önleme (soft limiter)
        miks = self._soft_limit(miks)

        # Kaydet
        try:
            Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)
            sf.write(cikis_yolu, miks, self._sr, subtype="PCM_24")

            sonuc.basarili = True
            sonuc.dosya_yolu = cikis_yolu
            sonuc.sure_ms = int(len(miks) / self._sr * 1000)
            logger.info("Basit ducking tamamlandı: %s", cikis_yolu)

        except Exception as e:
            sonuc.hata_mesaji = f"Kaydetme hatası: {e}"
            logger.error(sonuc.hata_mesaji)

        return sonuc

    def _envelope_olustur(
        self,
        toplam_ornek: int,
        dosya: AltyaziDosyasi,
    ) -> np.ndarray:
        """
        Altyazı zamanlarına göre ducking envelope dizisi oluşturur.

        Diyalog olan yerlerde duck_seviye, olmayan yerlerde 1.0 (tam ses).
        Geçişler attack/release ile yumuşatılır.

        Returns:
            float64 numpy dizisi (0.0–1.0 arası).
        """
        # dB'yi lineer çarpana dönüştür
        duck_carpan = 10 ** (self._duck_seviye_db / 20)

        # Başlangıçta her yer tam ses
        envelope = np.ones(toplam_ornek, dtype=np.float64)

        # Her altyazı satırı için ducking bölgesi işaretle
        for satir in dosya.satirlar:
            # Ducking başlangıcı: diyalogdan on_duck_ms önce
            duck_baslangic_ms = max(0, satir.baslangic_ms - self._on_duck_ms)
            duck_bitis_ms = satir.bitis_ms

            bas_ornek = int(self._sr * duck_baslangic_ms / 1000)
            bit_ornek = int(self._sr * duck_bitis_ms / 1000)

            bas_ornek = max(0, min(bas_ornek, toplam_ornek))
            bit_ornek = max(0, min(bit_ornek, toplam_ornek))

            if bas_ornek < bit_ornek:
                envelope[bas_ornek:bit_ornek] = duck_carpan

        # Attack ve release ile yumuşat (smoothing)
        envelope = self._envelope_yumusat(envelope)

        return envelope

    def _envelope_yumusat(self, envelope: np.ndarray) -> np.ndarray:
        """
        Envelope geçişlerini attack/release ile yumuşatır.

        Ani ses değişimlerini (click/pop) önlemek için üstel
        yumuşatma (exponential smoothing) uygular.
        """
        attack_ornek = max(1, int(self._sr * self._attack_ms / 1000))
        release_ornek = max(1, int(self._sr * self._release_ms / 1000))

        yumusak = np.copy(envelope)
        uzunluk = len(yumusak)

        i = 1
        while i < uzunluk:
            if yumusak[i] < yumusak[i - 1]:
                # Ses azalıyor → attack (hızlı düşüş)
                alfa = 1.0 / attack_ornek
                yumusak[i] = yumusak[i - 1] + alfa * (yumusak[i] - yumusak[i - 1])
            elif yumusak[i] > yumusak[i - 1]:
                # Ses artıyor → release (yavaş yükseliş)
                alfa = 1.0 / release_ornek
                yumusak[i] = yumusak[i - 1] + alfa * (yumusak[i] - yumusak[i - 1])
            i += 1

        return yumusak

    # --------------------------------------------------------
    # Yöntem 2: FFmpeg Sidechain Ducking
    # --------------------------------------------------------

    def sidechain_duck(
        self,
        orijinal_ses: str,
        tts_ses: str,
        cikis_yolu: str,
        sidechain_ayar: Optional[dict] = None,
    ) -> DuckingSonucu:
        """
        FFmpeg sidechaincompress filtresi ile ducking uygular.

        TTS ses kanalı tetikleyici olarak kullanılır. Orijinal ses,
        TTS sinyali algılandığında otomatik kısılır.

        Args:
            orijinal_ses: Orijinal video ses dosyası.
            tts_ses: TTS birleşik ses dosyası (tetikleyici).
            cikis_yolu: Mikslenen çıkış dosyası.
            sidechain_ayar: FFmpeg sidechain parametreleri.
                Varsayılan: threshold=0.02, ratio=4, attack=200, release=1000

        Returns:
            DuckingSonucu nesnesi.
        """
        sonuc = DuckingSonucu()
        sonuc.yontem = "sidechain"

        if sidechain_ayar is None:
            sidechain_ayar = {
                "threshold": 0.02,
                "ratio": 4,
                "attack": self._attack_ms,
                "release": self._release_ms * 2,
            }

        if not os.path.isfile(orijinal_ses):
            sonuc.hata_mesaji = f"Orijinal ses bulunamadı: {orijinal_ses}"
            return sonuc
        if not os.path.isfile(tts_ses):
            sonuc.hata_mesaji = f"TTS ses bulunamadı: {tts_ses}"
            return sonuc
        if not shutil.which("ffmpeg"):
            sonuc.hata_mesaji = "FFmpeg bulunamadı."
            return sonuc

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        # FFmpeg filter_complex:
        # [0:a] = orijinal ses (ducking uygulanacak)
        # [1:a] = TTS ses (sidechain tetikleyici + miksleme)
        threshold = sidechain_ayar.get("threshold", 0.02)
        ratio = sidechain_ayar.get("ratio", 4)
        attack = sidechain_ayar.get("attack", 200)
        release = sidechain_ayar.get("release", 1000)

        filtre = (
            f"[1:a]asplit[sc][tts];"
            f"[0:a][sc]sidechaincompress="
            f"threshold={threshold}:"
            f"ratio={ratio}:"
            f"attack={attack}:"
            f"release={release}"
            f"[ducked];"
            f"[ducked][tts]amix=inputs=2:duration=longest"
        )

        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", orijinal_ses,
                "-i", tts_ses,
                "-filter_complex", filtre,
                "-ar", str(self._sr),
                "-acodec", "pcm_s24le",
                cikis_yolu,
            ]

            proc = subprocess.run(cmd, capture_output=True, timeout=300)

            if proc.returncode == 0 and os.path.isfile(cikis_yolu):
                sonuc.basarili = True
                sonuc.dosya_yolu = cikis_yolu

                try:
                    bilgi = sf.info(cikis_yolu)
                    sonuc.sure_ms = int(bilgi.duration * 1000)
                except Exception:
                    pass

                logger.info("Sidechain ducking tamamlandı: %s", cikis_yolu)
            else:
                hata = proc.stderr.decode(errors="replace")[:300]
                sonuc.hata_mesaji = f"FFmpeg sidechain hatası: {hata}"
                logger.error(sonuc.hata_mesaji)

        except FileNotFoundError:
            sonuc.hata_mesaji = "FFmpeg bulunamadı."
        except subprocess.TimeoutExpired:
            sonuc.hata_mesaji = "FFmpeg zaman aşımı."
        except Exception as e:
            sonuc.hata_mesaji = f"Sidechain hatası: {e}"
            logger.error(sonuc.hata_mesaji)

        return sonuc

    # --------------------------------------------------------
    # Otomatik Yöntem Seçimi
    # --------------------------------------------------------

    def duck(
        self,
        orijinal_ses: str,
        tts_ses: str,
        cikis_yolu: str,
        dosya: Optional[AltyaziDosyasi] = None,
        yontem: str = "basit",
        sidechain_ayar: Optional[dict] = None,
    ) -> DuckingSonucu:
        """
        Belirtilen yöntemle ducking uygular.

        Args:
            orijinal_ses: Orijinal video ses dosyası.
            tts_ses: TTS birleşik ses dosyası.
            cikis_yolu: Çıkış dosyası.
            dosya: AltyaziDosyasi (basit yöntem için gerekli).
            yontem: "basit" veya "sidechain".
            sidechain_ayar: Sidechain parametreleri (sidechain yöntemi için).

        Returns:
            DuckingSonucu nesnesi.
        """
        if yontem == "sidechain":
            return self.sidechain_duck(
                orijinal_ses, tts_ses, cikis_yolu, sidechain_ayar
            )
        else:
            if dosya is None:
                sonuc = DuckingSonucu()
                sonuc.hata_mesaji = "Basit ducking için AltyaziDosyasi gerekli."
                return sonuc
            return self.basit_duck(
                orijinal_ses, tts_ses, dosya, cikis_yolu
            )

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    def _ses_oku(self, dosya_yolu: str) -> Optional[np.ndarray]:
        """
        Ses dosyasını mono float64 numpy dizisi olarak okur.
        Gerekirse resample ve stereo→mono dönüşümü yapar.
        """
        try:
            y, sr = sf.read(dosya_yolu, dtype="float64")

            # Stereo → mono
            if y.ndim > 1:
                y = np.mean(y, axis=1)

            # Resample
            if sr != self._sr:
                try:
                    import librosa
                    y = librosa.resample(y, orig_sr=sr, target_sr=self._sr)
                except ImportError:
                    oran = self._sr / sr
                    yeni_uzunluk = int(len(y) * oran)
                    x_eski = np.linspace(0, 1, len(y))
                    x_yeni = np.linspace(0, 1, yeni_uzunluk)
                    y = np.interp(x_yeni, x_eski, y)

            return y

        except Exception as e:
            logger.error("Ses okuma hatası (%s): %s", dosya_yolu, e)
            return None

    @staticmethod
    def _soft_limit(veri: np.ndarray, esik: float = 0.95) -> np.ndarray:
        """
        Yumuşak sınırlayıcı (soft limiter).

        Clipping yerine tanh bazlı yumuşak sınırlama uygular.
        Sesi daha doğal tutar.
        """
        peak = np.max(np.abs(veri))
        if peak <= esik:
            return veri

        # tanh bazlı soft clip
        veri = np.tanh(veri / esik) * esik
        return veri

    @staticmethod
    def ffmpeg_mevcut() -> bool:
        """FFmpeg'in PATH'te olup olmadığını kontrol eder."""
        return shutil.which("ffmpeg") is not None

    def __repr__(self) -> str:
        return (
            f"<AudioDucker seviye={self._duck_seviye_db}dB "
            f"attack={self._attack_ms}ms release={self._release_ms}ms "
            f"ön_duck={self._on_duck_ms}ms>"
        )
