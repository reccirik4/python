# -*- coding: utf-8 -*-
"""
DubSync Pro — OpenAI TTS Motor (openai_engine.py)

OpenAI'nin TTS API'sini kullanır.
Modeller: gpt-4o-mini-tts (en yeni, yönerge destekli),
          tts-1-hd (yüksek kalite), tts-1 (hızlı).
13 yerleşik ses: alloy, ash, ballad, coral, echo, fable, onyx,
                 nova, sage, shimmer, verse, marin, cedar.
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

logger = logging.getLogger("DubSync.OpenAIEngine")

# Yerleşik sesler ve cinsiyet tahminleri
OPENAI_SESLER = {
    "alloy":   {"cinsiyet": Cinsiyet.BELIRSIZ, "aciklama": "Nötr, dengeli"},
    "ash":     {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, güçlü"},
    "ballad":  {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, melodik"},
    "coral":   {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, sıcak"},
    "echo":    {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, derin"},
    "fable":   {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, anlatıcı"},
    "onyx":    {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, otoriter"},
    "nova":    {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, enerjik"},
    "sage":    {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, sakin"},
    "shimmer": {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, parlak"},
    "verse":   {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, ifadeli"},
    "marin":   {"cinsiyet": Cinsiyet.KADIN,    "aciklama": "Kadın, doğal (önerilen)"},
    "cedar":   {"cinsiyet": Cinsiyet.ERKEK,    "aciklama": "Erkek, doğal (önerilen)"},
}

OPENAI_MODELLER = ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"]


class OpenAIEngine(BaseEngine):
    """
    OpenAI TTS API motoru.

    Özellikler:
    - 3 model: gpt-4o-mini-tts, tts-1-hd, tts-1
    - 13 yerleşik ses
    - WAV/MP3/FLAC/AAC/OPUS çıkış
    - Hız ayarı 0.25x–4.0x
    - gpt-4o-mini-tts ile yönerge desteği (konuşma stili)
    - Çokdilli: Türkçe dahil 50+ dil

    Sınırlamalar:
    - Ücretli API (api_key gerekli)
    - İnternet bağlantısı gerekli
    - Ses klonlama: sadece custom voice API ile (ayrı süreç)
    """

    MOTOR_ADI = "openai"
    MOTOR_GORUNEN_AD = "OpenAI TTS"
    UCRETSIZ = False
    KLONLAMA_DESTEGI = False
    GPU_GEREKLI = False
    DESTEKLENEN_DILLER = [
        "tr", "en", "de", "fr", "es", "it", "pt", "ru", "ja", "ko",
        "zh", "ar", "hi", "nl", "pl", "sv", "da", "fi", "el", "cs",
    ]

    def __init__(self, ayarlar: Optional[dict] = None):
        super().__init__(ayarlar)
        self._client = None
        self._api_key: str = ""
        self._model: str = "tts-1-hd"
        self._varsayilan_ses: str = "onyx"

    # --------------------------------------------------------
    # Kullanılabilirlik Kontrolü
    # --------------------------------------------------------

    @classmethod
    def kullanilabilir_mi(cls) -> tuple[bool, str]:
        """openai paketinin yüklü olup olmadığını kontrol eder."""
        try:
            import openai  # noqa: F401
            return True, "openai paketi yüklü."
        except ImportError:
            return False, (
                "openai paketi yüklü değil. "
                "Kurulum: pip install openai"
            )

    # --------------------------------------------------------
    # Motor Yaşam Döngüsü
    # --------------------------------------------------------

    async def baslat(self) -> bool:
        """Motoru başlatır ve API bağlantısını doğrular."""
        try:
            import openai
        except ImportError as e:
            raise MotorBulunamadiHatasi(
                "openai paketi yüklü değil: pip install openai"
            ) from e

        self._api_key = self.ayar_al("api_key", "")
        self._model = self.ayar_al("model", "tts-1-hd")
        self._varsayilan_ses = self.ayar_al("varsayilan_ses", "onyx")

        if not self._api_key:
            logger.warning("OpenAI API anahtarı ayarlanmamış.")
            self._hazir = False
            return False

        try:
            self._client = openai.OpenAI(api_key=self._api_key)
            # Ses listesini oluştur
            self._sesler = self._sesleri_olustur()
            self._hazir = True
            logger.info(
                "OpenAI TTS başlatıldı: model=%s, %d ses",
                self._model, len(self._sesler),
            )
            return True

        except Exception as e:
            logger.error("OpenAI TTS başlatma hatası: %s", e)
            self._hazir = False
            return False

    async def kapat(self) -> None:
        """Motoru kapatır."""
        self._client = None
        self._hazir = False
        self._sesler = []
        logger.info("OpenAI TTS kapatıldı.")

    # --------------------------------------------------------
    # Ses Listeleme
    # --------------------------------------------------------

    def _sesleri_olustur(self) -> list[SesBilgisi]:
        """Yerleşik seslerden SesBilgisi listesi oluşturur."""
        sesler = []
        for ses_adi, bilgi in OPENAI_SESLER.items():
            ses = SesBilgisi(
                ses_id=ses_adi,
                isim=ses_adi.capitalize(),
                dil="multilingual",
                cinsiyet=bilgi["cinsiyet"],
                motor=self.MOTOR_ADI,
                aciklama=bilgi["aciklama"],
            )
            sesler.append(ses)
        return sesler

    async def sesleri_listele(self, dil_filtre: str = "") -> list[SesBilgisi]:
        """
        OpenAI sesleri çokdilli olduğu için dil filtresi uygulanmaz.
        Tüm sesler her dilde çalışır.
        """
        if not self._sesler:
            self._sesler = self._sesleri_olustur()
        return list(self._sesler)

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
        OpenAI TTS API ile metni seslendirir.

        Args:
            metin: Seslendirilecek metin.
            ses_id: Ses adı (örn: "onyx", "nova", "cedar").
            cikis_yolu: Çıkış dosya yolu (.wav veya .mp3).
            hiz: Hız ayarı ("+10%", "-20%" → 0.25–4.0 aralığına çevrilir).
            perde: Kullanılmaz (OpenAI API perde desteklemiyor).
            ses_seviyesi: Kullanılmaz.

        Returns:
            SesUretimSonucu nesnesi.
        """
        if not self._hazir or self._client is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="OpenAI TTS motoru başlatılmamış.",
                motor=self.MOTOR_ADI,
            )

        if not metin or not metin.strip():
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Boş metin.",
                motor=self.MOTOR_ADI,
            )

        if not ses_id:
            ses_id = self._varsayilan_ses

        # Hız dönüşümü: "+20%" → 1.2, "-30%" → 0.7
        hiz_carpan = self._hiz_cevir(hiz)

        # Çıkış formatı
        uzanti = Path(cikis_yolu).suffix.lower()
        format_map = {
            ".mp3": "mp3",
            ".wav": "wav",
            ".flac": "flac",
            ".aac": "aac",
            ".opus": "opus",
        }
        response_format = format_map.get(uzanti, "wav")

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        try:
            response = self._client.audio.speech.create(
                model=self._model,
                voice=ses_id,
                input=metin,
                response_format=response_format,
                speed=hiz_carpan,
            )

            # Dosyaya yaz
            response.stream_to_file(cikis_yolu)

            if not os.path.isfile(cikis_yolu):
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="OpenAI ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            sure_ms = self.ses_suresi_hesapla(cikis_yolu)

            return SesUretimSonucu(
                basarili=True,
                dosya_yolu=cikis_yolu,
                sure_ms=sure_ms,
                ornekleme_hizi=48000,
                motor=self.MOTOR_ADI,
            )

        except Exception as e:
            hata_str = str(e)

            # API anahtarı hatası
            if "invalid_api_key" in hata_str.lower() or "401" in hata_str:
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Geçersiz API anahtarı.",
                    motor=self.MOTOR_ADI,
                )

            # Kota aşımı
            if "429" in hata_str or "rate_limit" in hata_str.lower():
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="API kota aşımı. Lütfen bekleyin.",
                    motor=self.MOTOR_ADI,
                )

            # Yetersiz bakiye
            if "insufficient" in hata_str.lower() or "billing" in hata_str.lower():
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="Yetersiz API bakiyesi.",
                    motor=self.MOTOR_ADI,
                )

            logger.error("OpenAI TTS hatası: %s", e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"OpenAI API hatası: {hata_str[:200]}",
                motor=self.MOTOR_ADI,
            )

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @staticmethod
    def _hiz_cevir(hiz_str: str) -> float:
        """
        DubSync hız formatını OpenAI hız çarpanına çevirir.

        "+20%"  → 1.2
        "-30%"  → 0.7
        "+0%"   → 1.0

        OpenAI hız aralığı: 0.25–4.0
        """
        try:
            temiz = hiz_str.replace("%", "").replace("+", "").strip()
            yuzde = int(temiz) if temiz else 0
            carpan = 1.0 + (yuzde / 100.0)
            return max(0.25, min(4.0, carpan))
        except (ValueError, TypeError):
            return 1.0

    @property
    def model(self) -> str:
        """Aktif model adı."""
        return self._model

    @property
    def modeller(self) -> list[str]:
        """Kullanılabilir model listesi."""
        return list(OPENAI_MODELLER)
