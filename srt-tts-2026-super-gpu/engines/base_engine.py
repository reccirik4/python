# -*- coding: utf-8 -*-
"""
DubSync Pro — TTS Motor Temel Sınıfı (base_engine.py)

Tüm TTS motorlarının uygulaması gereken soyut arayüzü tanımlar.
Her motor (Edge TTS, XTTS-v2, OpenAI, ElevenLabs) bu sınıfı miras alır.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("DubSync.Engine")


# ============================================================
# Veri Yapıları
# ============================================================

class Cinsiyet(Enum):
    """Ses cinsiyeti."""
    ERKEK = "erkek"
    KADIN = "kadin"
    BELIRSIZ = "belirsiz"


@dataclass
class SesBilgisi:
    """Bir TTS sesinin bilgilerini temsil eder."""

    ses_id: str                         # Motor-spesifik ses kimliği (örn: "tr-TR-AhmetNeural")
    isim: str                           # Görünen isim (örn: "Ahmet")
    dil: str                            # Dil kodu (örn: "tr-TR", "en-US")
    cinsiyet: Cinsiyet = Cinsiyet.BELIRSIZ
    motor: str = ""                     # Motor adı (örn: "edge_tts")
    aciklama: str = ""                  # Ek açıklama
    onizleme_url: str = ""              # Varsa önizleme ses URL'si

    @property
    def etiket(self) -> str:
        """GUI'de gösterilecek etiket."""
        cinsiyet_str = "♂" if self.cinsiyet == Cinsiyet.ERKEK else "♀" if self.cinsiyet == Cinsiyet.KADIN else "?"
        return f"{self.isim} ({self.dil}) {cinsiyet_str}"


@dataclass
class SesUretimSonucu:
    """Bir TTS ses üretiminin sonucunu temsil eder."""

    basarili: bool                      # Üretim başarılı mı?
    dosya_yolu: str = ""                # Üretilen ses dosyasının yolu
    sure_ms: int = 0                    # Üretilen sesin süresi (milisaniye)
    ornekleme_hizi: int = 0             # Sample rate (Hz)
    hata_mesaji: str = ""               # Hata varsa açıklama
    motor: str = ""                     # Üreten motor adı

    @property
    def sure_sn(self) -> float:
        """Süreyi saniye olarak döndürür."""
        return self.sure_ms / 1000.0


class TTSHata(Exception):
    """TTS motor hatası temel sınıfı."""
    pass


class MotorBulunamadiHatasi(TTSHata):
    """Motor yüklü değil veya kullanılamıyor."""
    pass


class SesUretimHatasi(TTSHata):
    """Ses üretimi sırasında hata oluştu."""
    pass


class APIHatasi(TTSHata):
    """API anahtarı geçersiz veya API erişim hatası."""
    pass


# ============================================================
# Soyut Temel Sınıf
# ============================================================

class BaseEngine(ABC):
    """
    Tüm TTS motorlarının uygulaması gereken soyut temel sınıf.

    Her motor bu sınıfı miras almalı ve işaretli metotları uygulamalıdır.
    Ortak işlevler (dosya yolu oluşturma, loglama vb.) burada sağlanır.

    Kullanım:
        class EdgeEngine(BaseEngine):
            MOTOR_ADI = "edge_tts"
            MOTOR_GORUNEN_AD = "Microsoft Edge TTS"
            ...
    """

    # Alt sınıflar tarafından tanımlanmalı
    MOTOR_ADI: str = ""                 # Dahili ad (ayar dosyasındaki anahtar)
    MOTOR_GORUNEN_AD: str = ""          # GUI'de görünen ad
    UCRETSIZ: bool = True               # Ücretsiz mi?
    KLONLAMA_DESTEGI: bool = False       # Ses klonlama destekliyor mu?
    GPU_GEREKLI: bool = False            # GPU gerektirir mi?
    DESTEKLENEN_DILLER: list[str] = []   # Desteklenen dil kodları

    def __init__(self, ayarlar: Optional[dict] = None):
        """
        Args:
            ayarlar: Motor-spesifik ayar sözlüğü
                     (dubsync_pro_settings.json'dan).
        """
        self._ayarlar: dict = ayarlar or {}
        self._hazir: bool = False
        self._sesler: list[SesBilgisi] = []

    # --------------------------------------------------------
    # Soyut Metotlar (alt sınıflar UYGULAMALI)
    # --------------------------------------------------------

    @abstractmethod
    async def baslat(self) -> bool:
        """
        Motoru başlatır ve kullanıma hazırlar.

        API bağlantısı, model yükleme gibi işlemleri yapar.

        Returns:
            True: hazır, False: başlatılamadı.
        """
        ...

    @abstractmethod
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
        Metni sese dönüştürür ve dosyaya kaydeder.

        Args:
            metin: Seslendirilecek metin.
            ses_id: Kullanılacak ses kimliği (örn: "tr-TR-AhmetNeural").
            cikis_yolu: Çıkış ses dosyasının tam yolu (.wav veya .mp3).
            hiz: Konuşma hızı (örn: "+10%", "-20%").
            perde: Ses perdesi (örn: "+5Hz", "-10Hz").
            ses_seviyesi: Ses seviyesi (örn: "+10%", "-5%").

        Returns:
            SesUretimSonucu nesnesi.
        """
        ...

    @abstractmethod
    async def sesleri_listele(self, dil_filtre: str = "") -> list[SesBilgisi]:
        """
        Kullanılabilir seslerin listesini döndürür.

        Args:
            dil_filtre: Dil koduyla filtrele (örn: "tr" veya "tr-TR").
                        Boş string = tüm diller.

        Returns:
            SesBilgisi listesi.
        """
        ...

    @abstractmethod
    async def kapat(self) -> None:
        """
        Motoru kapatır ve kaynakları serbest bırakır.

        Model unload, bağlantı kapatma gibi temizlik işlemleri.
        """
        ...

    # --------------------------------------------------------
    # Opsiyonel: Ses Klonlama (destekleyen motorlar uygular)
    # --------------------------------------------------------

    async def ses_klonla(
        self,
        referans_ses_yolu: str,
        metin: str,
        cikis_yolu: str,
        dil: str = "tr",
    ) -> SesUretimSonucu:
        """
        Referans ses örneğini klonlayarak metni seslendirir.

        Args:
            referans_ses_yolu: Klonlanacak sesin dosya yolu (.wav).
            metin: Seslendirilecek metin.
            cikis_yolu: Çıkış dosya yolu.
            dil: Hedef dil kodu.

        Returns:
            SesUretimSonucu nesnesi.

        Raises:
            NotImplementedError: Motor klonlama desteklemiyorsa.
        """
        raise NotImplementedError(
            f"{self.MOTOR_GORUNEN_AD} ses klonlama desteklemiyor."
        )

    # --------------------------------------------------------
    # Ortak Yardımcılar
    # --------------------------------------------------------

    @property
    def hazir(self) -> bool:
        """Motor kullanıma hazır mı?"""
        return self._hazir

    @property
    def sesler(self) -> list[SesBilgisi]:
        """Önbelleğe alınmış ses listesi."""
        return self._sesler

    def ses_bul(self, ses_id: str) -> Optional[SesBilgisi]:
        """
        Ses kimliğine göre ses bilgisi bulur.

        Args:
            ses_id: Ses kimliği (örn: "tr-TR-AhmetNeural").

        Returns:
            SesBilgisi veya None.
        """
        for ses in self._sesler:
            if ses.ses_id == ses_id:
                return ses
        return None

    def dil_sesleri(self, dil_kodu: str) -> list[SesBilgisi]:
        """
        Belirtilen dildeki sesleri filtreler.

        Args:
            dil_kodu: "tr", "tr-TR", "en" gibi.

        Returns:
            Filtrelenmiş SesBilgisi listesi.
        """
        dil_kodu = dil_kodu.lower()
        return [
            s for s in self._sesler
            if s.dil.lower().startswith(dil_kodu)
        ]

    def ayar_al(self, anahtar: str, varsayilan=None):
        """Motor ayarından değer okur."""
        return self._ayarlar.get(anahtar, varsayilan)

    @staticmethod
    def cikis_yolu_olustur(
        hedef_klasor: str,
        satir_sira: int,
        motor_adi: str,
        uzanti: str = ".wav",
    ) -> str:
        """
        Ses dosyası için standart çıkış yolu oluşturur.

        Args:
            hedef_klasor: Hedef klasör yolu.
            satir_sira: Altyazı sıra numarası.
            motor_adi: Motor adı (dosya adına eklenir).
            uzanti: Dosya uzantısı.

        Returns:
            Tam dosya yolu (örn: "/output/segment_0001_edge_tts.wav").
        """
        Path(hedef_klasor).mkdir(parents=True, exist_ok=True)
        dosya_adi = f"segment_{satir_sira:04d}_{motor_adi}{uzanti}"
        return str(Path(hedef_klasor) / dosya_adi)

    @staticmethod
    def ses_suresi_hesapla(dosya_yolu: str) -> int:
        """
        Ses dosyasının süresini milisaniye olarak hesaplar.

        Args:
            dosya_yolu: Ses dosyasının yolu.

        Returns:
            Süre (milisaniye). Hata durumunda 0.
        """
        try:
            import soundfile as sf
            bilgi = sf.info(dosya_yolu)
            return int(bilgi.duration * 1000)
        except Exception as e:
            logger.warning("Ses süresi hesaplanamadı (%s): %s", dosya_yolu, e)
            return 0

    # --------------------------------------------------------
    # Kullanılabilirlik Kontrolü
    # --------------------------------------------------------

    @classmethod
    def kullanilabilir_mi(cls) -> tuple[bool, str]:
        """
        Motorun çalışma ortamında kullanılıp kullanılamayacağını kontrol eder.

        Gerekli kütüphaneler, API anahtarları, GPU durumu gibi
        ön koşulları kontrol eder.

        Returns:
            (kullanilabilir, mesaj) çifti.
            Örn: (True, "Hazır") veya (False, "edge-tts paketi yüklü değil").
        """
        return True, "Kontrol uygulanmamış."

    # --------------------------------------------------------
    # Temsil
    # --------------------------------------------------------

    def __repr__(self) -> str:
        durum = "hazır" if self._hazir else "beklemede"
        ses_sayisi = len(self._sesler)
        return (
            f"<{self.__class__.__name__} "
            f"motor='{self.MOTOR_ADI}' "
            f"durum={durum} "
            f"sesler={ses_sayisi}>"
        )
