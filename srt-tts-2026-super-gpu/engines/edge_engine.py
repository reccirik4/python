# -*- coding: utf-8 -*-
"""
DubSync Pro — Edge TTS Motor (edge_engine.py)

Microsoft Edge'in ücretsiz Neural TTS servisini kullanır.
İnternet bağlantısı gerektirir, API anahtarı gerektirmez.
Türkçe dahil 400+ ses destekler.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from engines.base_engine import (
    BaseEngine,
    SesBilgisi,
    SesUretimSonucu,
    Cinsiyet,
    SesUretimHatasi,
    MotorBulunamadiHatasi,
)

logger = logging.getLogger("DubSync.EdgeEngine")


class EdgeEngine(BaseEngine):
    """
    Microsoft Edge Neural TTS motoru.

    Özellikler:
    - Tamamen ücretsiz (API anahtarı yok).
    - 400+ neural ses, 100+ dil.
    - Türkçe: tr-TR-AhmetNeural (erkek), tr-TR-EmelNeural (kadın).
    - Hız, perde, ses seviyesi ayarlanabilir.
    - Async mimari (aiohttp WebSocket).
    - Çıkış: MP3 (otomatik WAV'a dönüştürülür).

    Sınırlamalar:
    - İnternet bağlantısı gerektirir.
    - Yoğun kullanımda rate limit uygulanabilir.
    - Ses klonlama desteklemiyor.
    - SSML desteği sınırlı (v5.0+ sonrası).
    """

    MOTOR_ADI = "edge_tts"
    MOTOR_GORUNEN_AD = "Microsoft Edge TTS"
    UCRETSIZ = True
    KLONLAMA_DESTEGI = False
    GPU_GEREKLI = False
    DESTEKLENEN_DILLER = [
        "tr-TR", "en-US", "en-GB", "de-DE", "fr-FR", "es-ES",
        "it-IT", "pt-BR", "ru-RU", "ja-JP", "ko-KR", "zh-CN",
        "ar-SA", "hi-IN", "nl-NL", "pl-PL", "sv-SE", "da-DK",
    ]

    # Türkçe varsayılan sesler
    TURKCE_ERKEK = "tr-TR-AhmetNeural"
    TURKCE_KADIN = "tr-TR-EmelNeural"

    def __init__(self, ayarlar: Optional[dict] = None):
        super().__init__(ayarlar)
        self._edge_tts = None  # edge_tts modülü (lazy import)

    # --------------------------------------------------------
    # Kullanılabilirlik Kontrolü
    # --------------------------------------------------------

    @classmethod
    def kullanilabilir_mi(cls) -> tuple[bool, str]:
        """edge-tts paketinin yüklü olup olmadığını kontrol eder."""
        try:
            import edge_tts  # noqa: F401
            return True, "edge-tts paketi yüklü ve hazır."
        except ImportError:
            return False, (
                "edge-tts paketi yüklü değil. "
                "Kurulum: pip install edge-tts"
            )

    # --------------------------------------------------------
    # Motor Yaşam Döngüsü
    # --------------------------------------------------------

    async def baslat(self) -> bool:
        """
        Motoru başlatır ve ses listesini yükler.

        Returns:
            True: başarılı.
        """
        try:
            import edge_tts
            self._edge_tts = edge_tts
        except ImportError as e:
            raise MotorBulunamadiHatasi(
                "edge-tts paketi yüklü değil: pip install edge-tts"
            ) from e

        # Ses listesini yükle
        try:
            sesler = await self._sesleri_yukle()
            self._sesler = sesler
            self._hazir = True
            logger.info(
                "Edge TTS başlatıldı: %d ses yüklendi.", len(sesler)
            )
            return True
        except Exception as e:
            logger.error("Edge TTS başlatma hatası: %s", e)
            self._hazir = False
            return False

    async def kapat(self) -> None:
        """Motoru kapatır (Edge TTS için özel temizlik gerekmez)."""
        self._hazir = False
        self._sesler = []
        self._edge_tts = None
        logger.info("Edge TTS kapatıldı.")

    # --------------------------------------------------------
    # Ses Listeleme
    # --------------------------------------------------------

    async def _sesleri_yukle(self) -> list[SesBilgisi]:
        """
        Microsoft'tan tüm mevcut sesleri çeker ve SesBilgisi'ne dönüştürür.

        Returns:
            SesBilgisi listesi.
        """
        voices_manager = await self._edge_tts.VoicesManager.create()
        sesler: list[SesBilgisi] = []

        for v in voices_manager.voices:
            kisa_ad = v.get("ShortName", "")
            tam_ad = v.get("FriendlyName", kisa_ad)
            dil = v.get("Locale", "")
            cinsiyet_str = v.get("Gender", "").lower()

            if cinsiyet_str == "male":
                cinsiyet = Cinsiyet.ERKEK
            elif cinsiyet_str == "female":
                cinsiyet = Cinsiyet.KADIN
            else:
                cinsiyet = Cinsiyet.BELIRSIZ

            # Görünen ismi sadeleştir
            gorunen_isim = kisa_ad
            if "Neural" in kisa_ad:
                # "tr-TR-AhmetNeural" → "Ahmet"
                parcalar = kisa_ad.split("-")
                if len(parcalar) >= 3:
                    gorunen_isim = parcalar[2].replace("Neural", "")

            ses = SesBilgisi(
                ses_id=kisa_ad,
                isim=gorunen_isim,
                dil=dil,
                cinsiyet=cinsiyet,
                motor=self.MOTOR_ADI,
                aciklama=tam_ad,
            )
            sesler.append(ses)

        return sesler

    async def sesleri_listele(self, dil_filtre: str = "") -> list[SesBilgisi]:
        """
        Sesleri listeler, opsiyonel dil filtresiyle.

        Args:
            dil_filtre: "tr", "tr-TR", "en" gibi.

        Returns:
            Filtrelenmiş SesBilgisi listesi.
        """
        if not self._sesler:
            self._sesler = await self._sesleri_yukle()

        if not dil_filtre:
            return list(self._sesler)

        dil_filtre = dil_filtre.lower()
        return [
            s for s in self._sesler
            if s.dil.lower().startswith(dil_filtre)
        ]

    # --------------------------------------------------------
    # Ses Üretimi
    # --------------------------------------------------------

    async def ses_uret(
        self,
        metin: str,
        ses_id: str,
        cikis_yolu: str,
        hiz: str = "+0%",
        perde: str = "+0Hz",
        ses_seviyesi: str = "+0%",
    ) -> SesUretimSonucu:
        """
        Metni Edge TTS ile seslendirir ve dosyaya kaydeder.

        Edge TTS MP3 üretir. Eğer çıkış yolu .wav ise otomatik dönüştürülür.

        Args:
            metin: Seslendirilecek metin.
            ses_id: Ses kimliği (örn: "tr-TR-AhmetNeural").
            cikis_yolu: Çıkış dosya yolu (.wav veya .mp3).
            hiz: Konuşma hızı (örn: "+10%", "-20%").
            perde: Ses perdesi (örn: "+5Hz").
            ses_seviyesi: Ses seviyesi (örn: "+10%").

        Returns:
            SesUretimSonucu nesnesi.
        """
        if not self._hazir or self._edge_tts is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Edge TTS motoru başlatılmamış.",
                motor=self.MOTOR_ADI,
            )

        if not metin or not metin.strip():
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Boş metin.",
                motor=self.MOTOR_ADI,
            )

        if not ses_id:
            ses_id = self.TURKCE_ERKEK

        # Çıkış dizinini oluştur
        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        # WAV isteniyorsa önce geçici MP3'e yaz
        wav_istendi = cikis_yolu.lower().endswith(".wav")
        if wav_istendi:
            mp3_yolu = cikis_yolu.rsplit(".", 1)[0] + ".mp3"
        else:
            mp3_yolu = cikis_yolu

        try:
            # edge_tts.Communicate ile ses üret
            communicate = self._edge_tts.Communicate(
                text=metin,
                voice=ses_id,
                rate=hiz,
                pitch=perde,
                volume=ses_seviyesi,
            )
            await communicate.save(mp3_yolu)

            if not os.path.isfile(mp3_yolu):
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Edge TTS ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            # WAV'a dönüştür (gerekirse)
            if wav_istendi:
                basarili = self._mp3_to_wav(mp3_yolu, cikis_yolu)
                # Geçici MP3'ü sil
                try:
                    os.remove(mp3_yolu)
                except OSError:
                    pass

                if not basarili:
                    return SesUretimSonucu(
                        basarili=False,
                        hata_mesaji="MP3→WAV dönüşümü başarısız.",
                        motor=self.MOTOR_ADI,
                    )

                son_dosya = cikis_yolu
            else:
                son_dosya = mp3_yolu

            # Süreyi hesapla
            sure_ms = self.ses_suresi_hesapla(son_dosya)

            # Örnekleme hızını al
            ornekleme_hizi = self._ornekleme_hizi_al(son_dosya)

            return SesUretimSonucu(
                basarili=True,
                dosya_yolu=son_dosya,
                sure_ms=sure_ms,
                ornekleme_hizi=ornekleme_hizi,
                motor=self.MOTOR_ADI,
            )

        except Exception as e:
            logger.error("Edge TTS ses üretim hatası: %s", e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Edge TTS hatası: {e}",
                motor=self.MOTOR_ADI,
            )

    # --------------------------------------------------------
    # MP3 → WAV Dönüşümü
    # --------------------------------------------------------

    @staticmethod
    def _mp3_to_wav(mp3_yolu: str, wav_yolu: str) -> bool:
        """
        MP3 dosyasını WAV'a dönüştürür.

        Öncelik sırasıyla dener:
        1. pydub (en yaygın)
        2. ffmpeg komut satırı
        3. librosa

        Args:
            mp3_yolu: Kaynak MP3 dosya yolu.
            wav_yolu: Hedef WAV dosya yolu.

        Returns:
            True: başarılı, False: başarısız.
        """
        # Yöntem 1: pydub
        try:
            from pydub import AudioSegment
            ses = AudioSegment.from_mp3(mp3_yolu)
            # 48kHz, 24-bit mono WAV olarak kaydet
            ses = ses.set_frame_rate(48000).set_channels(1).set_sample_width(3)
            ses.export(wav_yolu, format="wav")
            logger.debug("MP3→WAV dönüşümü (pydub): %s", wav_yolu)
            return True
        except Exception as e:
            logger.debug("pydub ile dönüşüm başarısız: %s", e)

        # Yöntem 2: ffmpeg komut satırı
        try:
            import subprocess
            sonuc = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", mp3_yolu,
                    "-ar", "48000",         # 48kHz
                    "-ac", "1",             # Mono
                    "-sample_fmt", "s32",   # 24-bit en yakın (s24 bazen sorun çıkarır)
                    "-acodec", "pcm_s24le", # 24-bit PCM
                    wav_yolu,
                ],
                capture_output=True,
                timeout=30,
            )
            if sonuc.returncode == 0 and os.path.isfile(wav_yolu):
                logger.debug("MP3→WAV dönüşümü (ffmpeg): %s", wav_yolu)
                return True
            logger.debug("ffmpeg hatası: %s", sonuc.stderr.decode(errors="replace")[:200])
        except Exception as e:
            logger.debug("ffmpeg ile dönüşüm başarısız: %s", e)

        # Yöntem 3: librosa
        try:
            import librosa
            import soundfile as sf
            y, sr = librosa.load(mp3_yolu, sr=48000, mono=True)
            sf.write(wav_yolu, y, 48000, subtype="PCM_24")
            logger.debug("MP3→WAV dönüşümü (librosa): %s", wav_yolu)
            return True
        except Exception as e:
            logger.debug("librosa ile dönüşüm başarısız: %s", e)

        logger.error("MP3→WAV dönüşümü tamamen başarısız: %s", mp3_yolu)
        return False

    @staticmethod
    def _ornekleme_hizi_al(dosya_yolu: str) -> int:
        """Ses dosyasının örnekleme hızını döndürür."""
        try:
            import soundfile as sf
            bilgi = sf.info(dosya_yolu)
            return bilgi.samplerate
        except Exception:
            return 0

    # --------------------------------------------------------
    # Yardımcı: Türkçe Ses Hızlı Erişim
    # --------------------------------------------------------

    def turkce_erkek_ses(self) -> str:
        """Türkçe erkek ses ID'si."""
        return self.ayar_al("varsayilan_ses_erkek", self.TURKCE_ERKEK)

    def turkce_kadin_ses(self) -> str:
        """Türkçe kadın ses ID'si."""
        return self.ayar_al("varsayilan_ses_kadin", self.TURKCE_KADIN)

    def turkce_sesler(self) -> list[SesBilgisi]:
        """Türkçe seslerin listesi."""
        return self.dil_sesleri("tr")
