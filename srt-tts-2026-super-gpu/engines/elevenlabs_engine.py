# -*- coding: utf-8 -*-
"""
DubSync Pro — ElevenLabs TTS Motor (elevenlabs_engine.py)

ElevenLabs'ın TTS API'sini kullanır.
Modeller: eleven_v3 (en yeni, 70+ dil), eleven_multilingual_v2,
          eleven_flash_v2_5 (düşük gecikme), eleven_turbo_v2_5.
10,000+ ses kütüphanesi, anında ses klonlama desteği.
API anahtarı gerektirir. Ücretli servis.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from engines.base_engine import (
    BaseEngine,
    SesBilgisi,
    SesUretimSonucu,
    Cinsiyet,
    APIHatasi,
    SesUretimHatasi,
    MotorBulunamadiHatasi,
)

logger = logging.getLogger("DubSync.ElevenLabsEngine")

ELEVENLABS_MODELLER = [
    "eleven_v3",
    "eleven_multilingual_v2",
    "eleven_flash_v2_5",
    "eleven_turbo_v2_5",
    "eleven_monolingual_v1",
]

# Yaygın çıkış formatları
# Format: codec_samplerate_bitrate
ELEVENLABS_FORMATLAR = {
    "mp3_44100_128": "MP3 44.1kHz 128kbps",
    "mp3_44100_192": "MP3 44.1kHz 192kbps",
    "pcm_24000":     "PCM 24kHz (WAV)",
    "pcm_44100":     "PCM 44.1kHz (WAV)",
}


class ElevenLabsEngine(BaseEngine):
    """
    ElevenLabs TTS API motoru.

    Özellikler:
    - Çokdilli: 70+ dil (eleven_v3), Türkçe dahil
    - 10,000+ ses kütüphanesi
    - Anında ses klonlama (IVC — Instant Voice Cloning)
    - Stabilite, benzerlik, stil kontrolleri
    - Streaming desteği
    - Audio tag'ler ([laughs], [whispers], [sighs])

    Sınırlamalar:
    - Ücretli API
    - İnternet bağlantısı gerekli
    - Ücretsiz planda sınırlı karakter kotası
    """

    MOTOR_ADI = "elevenlabs"
    MOTOR_GORUNEN_AD = "ElevenLabs"
    UCRETSIZ = False
    KLONLAMA_DESTEGI = True
    GPU_GEREKLI = False
    DESTEKLENEN_DILLER = [
        "tr", "en", "de", "fr", "es", "it", "pt", "ru", "ja", "ko",
        "zh", "ar", "hi", "nl", "pl", "sv", "da", "fi", "el", "cs",
        "id", "ro", "uk", "bg", "hr", "sk", "ta",
    ]

    def __init__(self, ayarlar: Optional[dict] = None):
        super().__init__(ayarlar)
        self._client = None
        self._api_key: str = ""
        self._model: str = "eleven_multilingual_v2"
        self._stabilite: float = 0.5
        self._benzerlik: float = 0.75
        self._stil: float = 0.0

    # --------------------------------------------------------
    # Kullanılabilirlik Kontrolü
    # --------------------------------------------------------

    @classmethod
    def kullanilabilir_mi(cls) -> tuple[bool, str]:
        """elevenlabs paketinin yüklü olup olmadığını kontrol eder."""
        try:
            from elevenlabs.client import ElevenLabs  # noqa: F401
            return True, "elevenlabs paketi yüklü."
        except ImportError:
            return False, (
                "elevenlabs paketi yüklü değil. "
                "Kurulum: pip install elevenlabs"
            )

    # --------------------------------------------------------
    # Motor Yaşam Döngüsü
    # --------------------------------------------------------

    async def baslat(self) -> bool:
        """Motoru başlatır ve API bağlantısını doğrular."""
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as e:
            raise MotorBulunamadiHatasi(
                "elevenlabs paketi yüklü değil: pip install elevenlabs"
            ) from e

        self._api_key = self.ayar_al("api_key", "")
        self._model = self.ayar_al("model", "eleven_multilingual_v2")
        self._stabilite = self.ayar_al("stabilite", 0.5)
        self._benzerlik = self.ayar_al("benzerlik", 0.75)
        self._stil = self.ayar_al("stil", 0.0)

        if not self._api_key:
            logger.warning("ElevenLabs API anahtarı ayarlanmamış.")
            self._hazir = False
            return False

        try:
            self._client = ElevenLabs(api_key=self._api_key)

            # Ses listesini API'den çek
            self._sesler = await self._sesleri_api_den_yukle()
            self._hazir = True

            logger.info(
                "ElevenLabs başlatıldı: model=%s, %d ses",
                self._model, len(self._sesler),
            )
            return True

        except Exception as e:
            logger.error("ElevenLabs başlatma hatası: %s", e)
            self._hazir = False
            return False

    async def kapat(self) -> None:
        """Motoru kapatır."""
        self._client = None
        self._hazir = False
        self._sesler = []
        logger.info("ElevenLabs kapatıldı.")

    # --------------------------------------------------------
    # Ses Listeleme
    # --------------------------------------------------------

    async def _sesleri_api_den_yukle(self) -> list[SesBilgisi]:
        """API'den kullanıcının erişebildiği sesleri çeker."""
        sesler: list[SesBilgisi] = []

        try:
            response = self._client.voices.search()
            voice_list = response.voices if hasattr(response, "voices") else []

            for v in voice_list:
                voice_id = getattr(v, "voice_id", "")
                name = getattr(v, "name", "")
                labels = getattr(v, "labels", {}) or {}

                # Cinsiyet tahmini
                gender_str = ""
                if isinstance(labels, dict):
                    gender_str = labels.get("gender", "").lower()
                elif hasattr(labels, "gender"):
                    gender_str = str(getattr(labels, "gender", "")).lower()

                if "male" in gender_str and "female" not in gender_str:
                    cinsiyet = Cinsiyet.ERKEK
                elif "female" in gender_str:
                    cinsiyet = Cinsiyet.KADIN
                else:
                    cinsiyet = Cinsiyet.BELIRSIZ

                # Dil tahmini
                dil = ""
                if isinstance(labels, dict):
                    dil = labels.get("language", "multilingual")

                ses = SesBilgisi(
                    ses_id=voice_id,
                    isim=name,
                    dil=dil or "multilingual",
                    cinsiyet=cinsiyet,
                    motor=self.MOTOR_ADI,
                    aciklama=getattr(v, "description", "") or "",
                )
                sesler.append(ses)

        except Exception as e:
            logger.warning("ElevenLabs ses listesi alınamadı: %s", e)

        return sesler

    async def sesleri_listele(self, dil_filtre: str = "") -> list[SesBilgisi]:
        """
        Kullanılabilir sesleri listeler.

        ElevenLabs sesleri çoğunlukla çokdilli olduğundan filtre
        labels'a göre yaklaşık uygulanır.
        """
        if not self._sesler and self._client:
            self._sesler = await self._sesleri_api_den_yukle()

        if not dil_filtre:
            return list(self._sesler)

        dil_filtre = dil_filtre.lower()
        return [
            s for s in self._sesler
            if dil_filtre in s.dil.lower() or s.dil.lower() == "multilingual"
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
        ElevenLabs API ile metni seslendirir.

        Args:
            metin: Seslendirilecek metin.
            ses_id: ElevenLabs voice_id.
            cikis_yolu: Çıkış dosya yolu.
            hiz: Kullanılmaz (ElevenLabs API hız kontrolü sınırlı).
            perde: Kullanılmaz.
            ses_seviyesi: Kullanılmaz.

        Returns:
            SesUretimSonucu nesnesi.
        """
        if not self._hazir or self._client is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="ElevenLabs motoru başlatılmamış.",
                motor=self.MOTOR_ADI,
            )

        if not metin or not metin.strip():
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Boş metin.",
                motor=self.MOTOR_ADI,
            )

        if not ses_id:
            # İlk mevcut sesi kullan
            if self._sesler:
                ses_id = self._sesler[0].ses_id
            else:
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Ses ID belirtilmemiş ve ses listesi boş.",
                    motor=self.MOTOR_ADI,
                )

        # Çıkış formatını belirle
        uzanti = Path(cikis_yolu).suffix.lower()
        if uzanti == ".wav":
            output_format = "pcm_44100"
        else:
            output_format = "mp3_44100_192"

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        try:
            # Ses üret
            audio_iterator = self._client.text_to_speech.convert(
                text=metin,
                voice_id=ses_id,
                model_id=self._model,
                output_format=output_format,
                voice_settings={
                    "stability": self._stabilite,
                    "similarity_boost": self._benzerlik,
                    "style": self._stil,
                },
            )

            # Iterator'dan bytes topla ve dosyaya yaz
            with open(cikis_yolu, "wb") as f:
                for chunk in audio_iterator:
                    if isinstance(chunk, bytes):
                        f.write(chunk)

            if not os.path.isfile(cikis_yolu) or os.path.getsize(cikis_yolu) == 0:
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="ElevenLabs ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            # PCM çıkış WAV header'a ihtiyaç duyar
            if output_format.startswith("pcm_"):
                self._pcm_to_wav(cikis_yolu, output_format)

            sure_ms = self.ses_suresi_hesapla(cikis_yolu)

            return SesUretimSonucu(
                basarili=True,
                dosya_yolu=cikis_yolu,
                sure_ms=sure_ms,
                ornekleme_hizi=44100,
                motor=self.MOTOR_ADI,
            )

        except Exception as e:
            hata_str = str(e)

            if "401" in hata_str or "invalid" in hata_str.lower():
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Geçersiz API anahtarı.",
                    motor=self.MOTOR_ADI,
                )

            if "429" in hata_str or "rate" in hata_str.lower():
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="API kota aşımı. Lütfen bekleyin.",
                    motor=self.MOTOR_ADI,
                )

            if "quota" in hata_str.lower() or "character" in hata_str.lower():
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Karakter kotası aşıldı.",
                    motor=self.MOTOR_ADI,
                )

            logger.error("ElevenLabs TTS hatası: %s", e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"ElevenLabs API hatası: {hata_str[:200]}",
                motor=self.MOTOR_ADI,
            )

    # --------------------------------------------------------
    # Ses Klonlama
    # --------------------------------------------------------

    async def ses_klonla(
        self,
        referans_ses_yolu: str,
        metin: str,
        cikis_yolu: str,
        dil: str = "tr",
    ) -> SesUretimSonucu:
        """
        Referans ses dosyasından klonlayarak seslendirir.

        Akış:
        1. Referans dosyadan IVC (Instant Voice Clone) oluştur.
        2. Klonlanan sesle metni seslendir.
        3. Geçici klonu sil (isteğe bağlı).

        Args:
            referans_ses_yolu: Klonlanacak sesin dosya yolu (.wav/.mp3).
            metin: Seslendirilecek metin.
            cikis_yolu: Çıkış dosya yolu.
            dil: Hedef dil kodu.

        Returns:
            SesUretimSonucu nesnesi.
        """
        if not self._hazir or self._client is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="ElevenLabs motoru başlatılmamış.",
                motor=self.MOTOR_ADI,
            )

        if not os.path.isfile(referans_ses_yolu):
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Referans ses bulunamadı: {referans_ses_yolu}",
                motor=self.MOTOR_ADI,
            )

        klon_voice_id = None

        try:
            # 1. IVC oluştur
            voice = self._client.voices.ivc.create(
                name=f"DubSync_Klon_{os.path.basename(referans_ses_yolu)}",
                files=[referans_ses_yolu],
            )
            klon_voice_id = voice.voice_id
            logger.info("Ses klonu oluşturuldu: %s", klon_voice_id)

            # 2. Klonlanan sesle üret
            sonuc = await self.ses_uret(
                metin=metin,
                ses_id=klon_voice_id,
                cikis_yolu=cikis_yolu,
            )

            return sonuc

        except Exception as e:
            logger.error("Ses klonlama hatası: %s", e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Klonlama hatası: {e}",
                motor=self.MOTOR_ADI,
            )

        finally:
            # 3. Geçici klonu sil (opsiyonel — kotayı boşaltmak için)
            if klon_voice_id:
                try:
                    self._client.voices.delete(klon_voice_id)
                    logger.debug("Geçici klon silindi: %s", klon_voice_id)
                except Exception:
                    logger.debug(
                        "Geçici klon silinemedi (manuel silinebilir): %s",
                        klon_voice_id,
                    )

    # --------------------------------------------------------
    # PCM → WAV Dönüşümü
    # --------------------------------------------------------

    @staticmethod
    def _pcm_to_wav(dosya_yolu: str, format_str: str):
        """
        ElevenLabs PCM çıkışını WAV header ile sarar.

        ElevenLabs pcm_XXXXX formatında raw PCM verir.
        Bu fonksiyon WAV header ekler.
        """
        import struct
        import wave

        # Sample rate'i format'tan çıkar
        try:
            sr = int(format_str.split("_")[1])
        except (IndexError, ValueError):
            sr = 44100

        # Raw PCM verisini oku
        with open(dosya_yolu, "rb") as f:
            pcm_data = f.read()

        # WAV olarak yeniden yaz
        with wave.open(dosya_yolu, "wb") as wav:
            wav.setnchannels(1)       # Mono
            wav.setsampwidth(2)       # 16-bit
            wav.setframerate(sr)
            wav.writeframes(pcm_data)

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def modeller(self) -> list[str]:
        return list(ELEVENLABS_MODELLER)

    @property
    def stabilite(self) -> float:
        return self._stabilite

    @property
    def benzerlik(self) -> float:
        return self._benzerlik
