# -*- coding: utf-8 -*-
"""
DubSync Pro — XTTS-v2 Motor (xtts_engine.py)

Coqui AI'nin XTTS-v2 modelini lokal olarak çalıştırır.
6 saniyelik ses örneğiyle zero-shot ses klonlama yapar.
GPU önerilir (min 4GB VRAM). CPU'da da çalışır (yavaş).
17 dil: Türkçe (tr) dahil.
Ücretsiz, lokal, internet gerektirmez (model indirildikten sonra).
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
    MotorBulunamadiHatasi,
    SesUretimHatasi,
)

logger = logging.getLogger("DubSync.XTTSEngine")

MODEL_ADI = "tts_models/multilingual/multi-dataset/xtts_v2"

XTTS_DILLER = {
    "en": "İngilizce",
    "es": "İspanyolca",
    "fr": "Fransızca",
    "de": "Almanca",
    "it": "İtalyanca",
    "pt": "Portekizce",
    "pl": "Lehçe",
    "tr": "Türkçe",
    "ru": "Rusça",
    "nl": "Felemenkçe",
    "cs": "Çekçe",
    "ar": "Arapça",
    "zh-cn": "Çince",
    "ja": "Japonca",
    "hu": "Macarca",
    "ko": "Korece",
    "hi": "Hintçe",
}


class XTTSEngine(BaseEngine):
    """
    Coqui XTTS-v2 lokal ses klonlama motoru.

    Özellikler:
    - 6 saniyelik ses örneğiyle zero-shot klonlama
    - 17 dil desteği (Türkçe dahil)
    - Cross-language klonlama (bir dildeki sesle başka dilde konuşturma)
    - GPU ile hızlı üretim (~3x gerçek zamandan hızlı)
    - Tamamen lokal, internet gerektirmez
    - Ücretsiz (Coqui Public Model License)

    Gereksinimler:
    - pip install coqui-tts (veya TTS)
    - PyTorch CUDA (GPU için): pip install torch torchaudio --index-url ...cu121
    - Min 4GB VRAM (GPU) veya 8GB RAM (CPU, yavaş)
    - İlk çalıştırmada model indirilir (~1.8GB)
    """

    MOTOR_ADI = "xtts_v2"
    MOTOR_GORUNEN_AD = "XTTS-v2 (Lokal Klonlama)"
    UCRETSIZ = True
    KLONLAMA_DESTEGI = True
    GPU_GEREKLI = False  # Önerilen ama zorunlu değil
    DESTEKLENEN_DILLER = list(XTTS_DILLER.keys())

    def __init__(self, ayarlar: Optional[dict] = None):
        super().__init__(ayarlar)
        self._tts = None
        self._device: str = "cpu"
        self._dil: str = "tr"
        self._varsayilan_referans: str = ""

    # --------------------------------------------------------
    # Kullanılabilirlik Kontrolü
    # --------------------------------------------------------

    @classmethod
    def kullanilabilir_mi(cls) -> tuple[bool, str]:
        """TTS paketinin yüklü olup olmadığını kontrol eder."""
        try:
            from TTS.api import TTS  # noqa: F401
            return True, "coqui-tts paketi yüklü."
        except ImportError:
            return False, (
                "coqui-tts paketi yüklü değil. "
                "Kurulum: pip install coqui-tts>=0.27.0"
            )
        except OSError:
            return False, (
                "coqui-tts DLL hatası. Çözüm:\n"
                "  pip uninstall torch torchaudio -y\n"
                "  pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cpu"
            )
        except Exception as e:
            return False, f"coqui-tts yükleme hatası: {e}"

    @staticmethod
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
            return False

    # --------------------------------------------------------
    # Motor Yaşam Döngüsü
    # --------------------------------------------------------

    async def baslat(self) -> bool:
        """
        Modeli yükler ve hazırlar.

        İlk çalıştırmada model otomatik indirilir (~1.8GB).
        GPU uyumluysa CUDA'ya taşınır, yoksa CPU'da çalışır.
        GPU testi başarısız olursa otomatik olarak CPU moduna düşer.
        """
        try:
            from TTS.api import TTS
        except ImportError as e:
            raise MotorBulunamadiHatasi(
                "coqui-tts paketi yüklü değil: pip install coqui-tts>=0.27.0"
            ) from e
        except OSError as e:
            raise MotorBulunamadiHatasi(
                f"coqui-tts DLL hatası: {e}\n"
                "Çözüm: pip uninstall torch torchaudio -y && "
                "pip install torch torchaudio "
                "--index-url https://download.pytorch.org/whl/cpu"
            ) from e

        self._dil = self.ayar_al("dil", "tr")
        gpu_kullan = self.ayar_al("gpu_kullan", True)
        self._varsayilan_referans = self.ayar_al("referans_ses_klasoru", "")

        # Cihaz seçimi — GPU testi başarısızsa CPU'ya düşer
        if gpu_kullan and self.gpu_mevcut():
            self._device = "cuda"
        else:
            self._device = "cpu"
            if gpu_kullan:
                logger.info(
                    "CPU modu kullanılacak (GPU uyumsuz veya mevcut değil). "
                    "XTTS CPU'da yavaş çalışır ama ses kalitesi aynıdır."
                )

        try:
            logger.info(
                "XTTS-v2 yükleniyor (cihaz=%s)... İlk seferde model indirilir (~1.8GB).",
                self._device,
            )

            # Model yolu belirtilmişse onu kullan, yoksa otomatik indir
            model_yolu = self.ayar_al("model_yolu", "")
            if model_yolu and os.path.isdir(model_yolu):
                self._tts = TTS(
                    model_path=model_yolu,
                    config_path=os.path.join(model_yolu, "config.json"),
                ).to(self._device)
            else:
                self._tts = TTS(MODEL_ADI).to(self._device)

            # Ses listesini oluştur (XTTS'de preset speaker yok, klonlama bazlı)
            self._sesler = self._sesleri_olustur()
            self._hazir = True

            logger.info(
                "XTTS-v2 hazır: cihaz=%s, dil=%s",
                self._device, self._dil,
            )
            return True

        except OSError as e:
            logger.error("XTTS-v2 DLL/OS hatası: %s", e)
            self._hazir = False
            return False

        except Exception as e:
            logger.error("XTTS-v2 yükleme hatası: %s", e)
            self._hazir = False
            return False

    async def kapat(self) -> None:
        """Modeli bellekten kaldırır."""
        if self._tts is not None:
            del self._tts
            self._tts = None

            # GPU belleğini temizle
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

        self._hazir = False
        self._sesler = []
        logger.info("XTTS-v2 kapatıldı, bellek temizlendi.")

    # --------------------------------------------------------
    # Ses Listeleme
    # --------------------------------------------------------

    def _sesleri_olustur(self) -> list[SesBilgisi]:
        """
        XTTS için sanal ses listesi oluşturur.

        XTTS'de preset sesler yok — tamamen klonlama bazlı.
        Bu yüzden referans ses klasöründeki dosyaları listeler.
        """
        sesler = []

        # Bilgi girdisi: XTTS klonlama bazlı
        sesler.append(SesBilgisi(
            ses_id="xtts_clone",
            isim="Klonlama (referans ses gerekli)",
            dil="multilingual",
            cinsiyet=Cinsiyet.BELIRSIZ,
            motor=self.MOTOR_ADI,
            aciklama="6 saniyelik ses örneğiyle klonlama",
        ))

        # Referans ses klasöründeki dosyaları tara
        if self._varsayilan_referans and os.path.isdir(self._varsayilan_referans):
            for dosya in sorted(os.listdir(self._varsayilan_referans)):
                if dosya.lower().endswith((".wav", ".mp3", ".ogg", ".flac")):
                    dosya_yolu = os.path.join(self._varsayilan_referans, dosya)
                    ad = Path(dosya).stem
                    sesler.append(SesBilgisi(
                        ses_id=dosya_yolu,
                        isim=f"Klon: {ad}",
                        dil="multilingual",
                        cinsiyet=Cinsiyet.BELIRSIZ,
                        motor=self.MOTOR_ADI,
                        aciklama=f"Referans: {dosya}",
                    ))

        return sesler

    async def sesleri_listele(self, dil_filtre: str = "") -> list[SesBilgisi]:
        """XTTS tüm dillerde klonlama yapabilir, filtre uygulanmaz."""
        if not self._sesler:
            self._sesler = self._sesleri_olustur()
        return list(self._sesler)

    # --------------------------------------------------------
    # Ses Üretimi (Klonlama)
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
        XTTS-v2 ile klonlama bazlı ses üretimi.

        ses_id, referans ses dosyasının yolunu içerir.
        Eğer ses_id bir dosya yolu değilse, varsayılan referansı kullanır.

        Args:
            metin: Seslendirilecek metin.
            ses_id: Referans ses dosya yolu veya "xtts_clone".
            cikis_yolu: Çıkış WAV dosya yolu.
            hiz: Kullanılmaz (XTTS hız kontrolü yok).
            perde: Kullanılmaz.
            ses_seviyesi: Kullanılmaz.
        """
        if not self._hazir or self._tts is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="XTTS-v2 motoru başlatılmamış.",
                motor=self.MOTOR_ADI,
            )

        if not metin or not metin.strip():
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Boş metin.",
                motor=self.MOTOR_ADI,
            )

        # Referans ses dosyasını belirle
        referans_yolu = self._referans_bul(ses_id)
        if not referans_yolu:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=(
                    "Referans ses dosyası bulunamadı. "
                    "XTTS-v2 klonlama için bir ses örneği gereklidir."
                ),
                motor=self.MOTOR_ADI,
            )

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        try:
            self._tts.tts_to_file(
                text=metin,
                speaker_wav=referans_yolu,
                language=self._dil,
                file_path=cikis_yolu,
            )

            if not os.path.isfile(cikis_yolu):
                return SesUretimSonucu(
                    basarili=False,
                    hata_mesaji="XTTS ses dosyası oluşturulamadı.",
                    motor=self.MOTOR_ADI,
                )

            sure_ms = self.ses_suresi_hesapla(cikis_yolu)

            return SesUretimSonucu(
                basarili=True,
                dosya_yolu=cikis_yolu,
                sure_ms=sure_ms,
                ornekleme_hizi=24000,  # XTTS-v2 çıkış: 24kHz
                motor=self.MOTOR_ADI,
            )

        except Exception as e:
            logger.error("XTTS ses üretim hatası: %s", e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"XTTS hatası: {e}",
                motor=self.MOTOR_ADI,
            )

    # --------------------------------------------------------
    # Ses Klonlama (BaseEngine override)
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

        XTTS-v2 zaten klonlama bazlı olduğundan ses_uret ile
        aynı işlevi görür. Ek olarak dil parametresi alır.
        """
        eski_dil = self._dil
        self._dil = dil

        sonuc = await self.ses_uret(
            metin=metin,
            ses_id=referans_ses_yolu,
            cikis_yolu=cikis_yolu,
        )

        self._dil = eski_dil
        return sonuc

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    def _referans_bul(self, ses_id: str) -> Optional[str]:
        """
        Referans ses dosyasını bulur.

        Öncelik:
        1. ses_id bir dosya yoluysa ve mevcutsa → onu kullan
        2. Referans ses klasöründe ara
        3. Varsayılan referans

        Returns:
            Dosya yolu veya None.
        """
        # ses_id doğrudan bir dosya yolu mu?
        if ses_id and os.path.isfile(ses_id):
            return ses_id

        # Referans klasöründe ara
        if self._varsayilan_referans and os.path.isdir(self._varsayilan_referans):
            # İlk uygun dosyayı bul
            for dosya in sorted(os.listdir(self._varsayilan_referans)):
                if dosya.lower().endswith((".wav", ".mp3", ".ogg", ".flac")):
                    return os.path.join(self._varsayilan_referans, dosya)

        return None

    @property
    def device(self) -> str:
        """Aktif cihaz (cuda/cpu)."""
        return self._device

    @property
    def dil(self) -> str:
        """Aktif dil kodu."""
        return self._dil

    @dil.setter
    def dil(self, yeni_dil: str):
        """Dil kodunu günceller."""
        if yeni_dil in XTTS_DILLER:
            self._dil = yeni_dil
        else:
            logger.warning("Desteklenmeyen dil: %s", yeni_dil)

    @property
    def desteklenen_diller(self) -> dict[str, str]:
        """Desteklenen diller ve Türkçe adları."""
        return dict(XTTS_DILLER)
