# -*- coding: utf-8 -*-
"""
DubSync Pro — TTS Motor Yöneticisi (tts_manager.py)

Tüm TTS motorlarını merkezi olarak yönetir.
Karakter-motor eşlemesi, toplu ses üretimi ve ilerleme takibi sağlar.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Callable

from core.config_manager import ConfigManager
from core.srt_parser import AltyaziSatiri, AltyaziDosyasi
from engines.base_engine import (
    BaseEngine,
    SesUretimSonucu,
    SesBilgisi,
    TTSHata,
    MotorBulunamadiHatasi,
    SesUretimHatasi,
)

logger = logging.getLogger("DubSync.TTSManager")


# ============================================================
# İlerleme Durumu
# ============================================================

class IlerlemeDurumu:
    """Toplu ses üretimi sırasında ilerleme bilgisini tutar."""

    def __init__(self, toplam: int):
        self.toplam: int = toplam
        self.tamamlanan: int = 0
        self.basarili: int = 0
        self.hatali: int = 0
        self.atlanan: int = 0
        self.mevcut_satir: Optional[AltyaziSatiri] = None
        self.iptal: bool = False
        self.duraklatildi: bool = False

    @property
    def yuzde(self) -> float:
        if self.toplam == 0:
            return 0.0
        return (self.tamamlanan / self.toplam) * 100.0

    @property
    def kalan(self) -> int:
        return max(0, self.toplam - self.tamamlanan)

    def __repr__(self) -> str:
        return (
            f"<İlerleme {self.tamamlanan}/{self.toplam} "
            f"(%{self.yuzde:.1f}) "
            f"başarılı={self.basarili} hatalı={self.hatali}>"
        )


# ============================================================
# TTS Motor Yöneticisi
# ============================================================

class TTSManager:
    """
    Merkezi TTS motor yöneticisi.

    - Motorları kaydeder ve yaşam döngülerini yönetir.
    - Karakter → motor + ses eşlemesi yapar.
    - Toplu ses üretimini koordine eder.
    - İlerleme geri çağrımları sağlar.

    Kullanım:
        manager = TTSManager(config)
        await manager.motorlari_baslat()
        sonuclar = await manager.toplu_uret(dosya, cikis_klasoru)
        await manager.motorlari_kapat()
    """

    def __init__(self, config: ConfigManager):
        """
        Args:
            config: ConfigManager nesnesi.
        """
        self._config = config
        self._motorlar: dict[str, BaseEngine] = {}  # {motor_adi: motor_nesnesi}
        self._ilerleme: Optional[IlerlemeDurumu] = None
        self._ilerleme_callback: Optional[Callable[[IlerlemeDurumu], None]] = None

    # --------------------------------------------------------
    # Motor Kaydı ve Yaşam Döngüsü
    # --------------------------------------------------------

    def motor_kaydet(self, motor: BaseEngine) -> None:
        """
        TTS motorunu yöneticiye kaydeder.

        Args:
            motor: BaseEngine alt sınıfı örneği.
        """
        ad = motor.MOTOR_ADI
        if not ad:
            raise ValueError("Motor adı boş olamaz.")
        self._motorlar[ad] = motor
        logger.info("Motor kaydedildi: %s (%s)", ad, motor.MOTOR_GORUNEN_AD)

    def motor_al(self, motor_adi: str) -> Optional[BaseEngine]:
        """
        Kayıtlı motoru döndürür.

        Args:
            motor_adi: Motor adı (örn: "edge_tts").

        Returns:
            BaseEngine örneği veya None.
        """
        return self._motorlar.get(motor_adi)

    def kayitli_motorlar(self) -> dict[str, BaseEngine]:
        """Tüm kayıtlı motorları döndürür."""
        return dict(self._motorlar)

    def kullanilabilir_motorlar(self) -> list[str]:
        """Kullanılabilir (kontrol geçen) motor adlarını döndürür."""
        sonuc = []
        for ad, motor in self._motorlar.items():
            kullanilabilir, _ = motor.__class__.kullanilabilir_mi()
            if kullanilabilir:
                sonuc.append(ad)
        return sonuc

    async def motorlari_baslat(self) -> dict[str, bool]:
        """
        Tüm aktif motorları başlatır.

        Returns:
            {motor_adi: basarili} sözlüğü.
        """
        aktif_motor_adlari = self._config.aktif_motorlar()
        sonuclar: dict[str, bool] = {}

        for ad in aktif_motor_adlari:
            motor = self._motorlar.get(ad)
            if motor is None:
                logger.warning("Motor kayıtlı değil, atlanıyor: %s", ad)
                sonuclar[ad] = False
                continue

            try:
                basarili = await motor.baslat()
                sonuclar[ad] = basarili
                if basarili:
                    logger.info("Motor başlatıldı: %s", ad)
                else:
                    logger.warning("Motor başlatılamadı: %s", ad)
            except Exception as e:
                logger.error("Motor başlatma hatası (%s): %s", ad, e)
                sonuclar[ad] = False

        return sonuclar

    async def motorlari_kapat(self) -> None:
        """Tüm motorları kapatır ve kaynakları serbest bırakır."""
        for ad, motor in self._motorlar.items():
            try:
                await motor.kapat()
                logger.info("Motor kapatıldı: %s", ad)
            except Exception as e:
                logger.warning("Motor kapatma hatası (%s): %s", ad, e)

    # --------------------------------------------------------
    # Ses Listeleme
    # --------------------------------------------------------

    async def tum_sesleri_listele(self, dil_filtre: str = "") -> dict[str, list[SesBilgisi]]:
        """
        Tüm aktif motorlardan sesleri toplar.

        Args:
            dil_filtre: Dil koduyla filtrele (örn: "tr"). Boş = tüm diller.

        Returns:
            {motor_adi: [SesBilgisi, ...]} sözlüğü.
        """
        sonuc: dict[str, list[SesBilgisi]] = {}

        for ad, motor in self._motorlar.items():
            if not motor.hazir:
                continue
            try:
                sesler = await motor.sesleri_listele(dil_filtre)
                sonuc[ad] = sesler
            except Exception as e:
                logger.warning("Ses listesi alınamadı (%s): %s", ad, e)
                sonuc[ad] = []

        return sonuc

    async def turkce_sesleri_listele(self) -> dict[str, list[SesBilgisi]]:
        """Türkçe sesleri tüm motorlardan toplar."""
        return await self.tum_sesleri_listele("tr")

    # --------------------------------------------------------
    # Karakter-Motor Eşlemesi
    # --------------------------------------------------------

    def karakter_icin_motor_ve_ses(
        self, karakter_id: str
    ) -> tuple[Optional[BaseEngine], str, dict]:
        """
        Karakter için atanmış motor ve ses bilgisini döndürür.

        Öncelik:
        1. Karakter ayarında tanımlı motor+ses
        2. Varsayılan motor + cinsiyete göre ses

        Args:
            karakter_id: Konuşmacı kimliği (örn: "SPEAKER_00").

        Returns:
            (motor, ses_id, ek_parametreler) üçlüsü.
            Motor bulunamazsa (None, "", {}) döner.
        """
        karakter = self._config.karakter_al(karakter_id)

        if karakter:
            motor_adi = karakter.get("motor", "")
            ses_id = karakter.get("ses", "")
            klon_yolu = karakter.get("klon_yolu", "")
            ek = {
                "hiz": karakter.get("hiz", "+0%"),
                "perde": karakter.get("perde", "+0Hz"),
                "klon_yolu": klon_yolu,
            }

            # XTTS: ses_id dosya yolu değilse, klon_yolu'nu kullan
            if motor_adi == "xtts_v2" and klon_yolu and os.path.isfile(klon_yolu):
                ses_id = klon_yolu
        else:
            # Karakter tanımlanmamış, varsayılanı kullan
            motor_adi = self._config.varsayilan_motor()
            ses_id = ""
            ek = {"hiz": "+0%", "perde": "+0Hz"}

        if not motor_adi:
            motor_adi = self._config.varsayilan_motor()

        motor = self._motorlar.get(motor_adi)
        if motor is None:
            logger.warning(
                "Karakter '%s' için motor bulunamadı: '%s'", karakter_id, motor_adi
            )
            # Herhangi bir hazır motoru kullan (fallback)
            for ad, m in self._motorlar.items():
                if m.hazir:
                    motor = m
                    motor_adi = ad
                    logger.info("Fallback motor kullanılıyor: %s", ad)
                    break

        if motor is None:
            return None, "", {}

        # Ses ID boşsa motorun varsayılanını kullan
        if not ses_id:
            cinsiyet = "kadin" if karakter and karakter.get("cinsiyet") == "kadin" else "erkek"
            ses_id = self._config._varsayilan_ses_bul(motor_adi, cinsiyet)

        return motor, ses_id, ek

    # --------------------------------------------------------
    # Tekil Ses Üretimi
    # --------------------------------------------------------

    async def satir_seslendir(
        self,
        satir: AltyaziSatiri,
        cikis_klasoru: str,
    ) -> SesUretimSonucu:
        """
        Tek bir altyazı satırını seslendirir.

        Args:
            satir: AltyaziSatiri nesnesi.
            cikis_klasoru: Çıkış klasörü.

        Returns:
            SesUretimSonucu nesnesi.
        """
        if not satir.temiz_metin.strip():
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji="Boş metin, atlandı.",
                motor="",
            )

        motor, ses_id, ek = self.karakter_icin_motor_ve_ses(satir.konusmaci_id)

        if motor is None:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Konuşmacı '{satir.konusmaci_id}' için motor bulunamadı.",
                motor="",
            )

        if not motor.hazir:
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Motor hazır değil: {motor.MOTOR_ADI}",
                motor=motor.MOTOR_ADI,
            )

        cikis_yolu = BaseEngine.cikis_yolu_olustur(
            cikis_klasoru, satir.sira, motor.MOTOR_ADI
        )

        try:
            sonuc = await motor.ses_uret(
                metin=satir.temiz_metin,
                ses_id=ses_id,
                cikis_yolu=cikis_yolu,
                hiz=ek.get("hiz", "+0%"),
                perde=ek.get("perde", "+0Hz"),
            )
            return sonuc

        except TTSHata as e:
            logger.error("Satır %d ses üretim hatası: %s", satir.sira, e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=str(e),
                motor=motor.MOTOR_ADI,
            )
        except Exception as e:
            logger.error("Satır %d beklenmeyen hata: %s", satir.sira, e)
            return SesUretimSonucu(
                basarili=False,
                hata_mesaji=f"Beklenmeyen hata: {e}",
                motor=motor.MOTOR_ADI,
            )

    # --------------------------------------------------------
    # Toplu Ses Üretimi
    # --------------------------------------------------------

    async def toplu_uret(
        self,
        dosya: AltyaziDosyasi,
        cikis_klasoru: str,
        ilerleme_callback: Optional[Callable[[IlerlemeDurumu], None]] = None,
    ) -> list[tuple[AltyaziSatiri, SesUretimSonucu]]:
        """
        Tüm altyazı satırlarını sırayla seslendirir.

        Args:
            dosya: AltyaziDosyasi nesnesi.
            cikis_klasoru: Çıkış klasörü.
            ilerleme_callback: Her satır sonrası çağrılacak fonksiyon.

        Returns:
            [(AltyaziSatiri, SesUretimSonucu), ...] listesi.
        """
        Path(cikis_klasoru).mkdir(parents=True, exist_ok=True)

        self._ilerleme = IlerlemeDurumu(toplam=dosya.satir_sayisi)
        self._ilerleme_callback = ilerleme_callback
        sonuclar: list[tuple[AltyaziSatiri, SesUretimSonucu]] = []

        logger.info(
            "Toplu üretim başlıyor: %d satır, çıkış: %s",
            dosya.satir_sayisi,
            cikis_klasoru,
        )

        for satir in dosya.satirlar:
            # İptal kontrolü
            if self._ilerleme.iptal:
                logger.info("Toplu üretim iptal edildi.")
                break

            # Duraklatma kontrolü
            while self._ilerleme.duraklatildi:
                await asyncio.sleep(0.2)
                if self._ilerleme.iptal:
                    break

            self._ilerleme.mevcut_satir = satir

            sonuc = await self.satir_seslendir(satir, cikis_klasoru)
            sonuclar.append((satir, sonuc))

            # İstatistikleri güncelle
            self._ilerleme.tamamlanan += 1
            if sonuc.basarili:
                self._ilerleme.basarili += 1
            elif "Boş metin" in sonuc.hata_mesaji:
                self._ilerleme.atlanan += 1
            else:
                self._ilerleme.hatali += 1

            # Geri çağrım
            if self._ilerleme_callback:
                try:
                    self._ilerleme_callback(self._ilerleme)
                except Exception as e:
                    logger.warning("İlerleme callback hatası: %s", e)

        logger.info(
            "Toplu üretim tamamlandı: %d başarılı, %d hatalı, %d atlanan",
            self._ilerleme.basarili,
            self._ilerleme.hatali,
            self._ilerleme.atlanan,
        )

        return sonuclar

    # --------------------------------------------------------
    # Kontrol
    # --------------------------------------------------------

    def iptal_et(self) -> None:
        """Devam eden toplu üretimi iptal eder."""
        if self._ilerleme:
            self._ilerleme.iptal = True
            logger.info("İptal isteği gönderildi.")

    def duraksat(self) -> None:
        """Toplu üretimi duraklatır."""
        if self._ilerleme:
            self._ilerleme.duraklatildi = True
            logger.info("Duraklatma isteği gönderildi.")

    def devam_et(self) -> None:
        """Duraklatılmış üretimi devam ettirir."""
        if self._ilerleme:
            self._ilerleme.duraklatildi = False
            logger.info("Devam ettiriliyor.")

    @property
    def ilerleme(self) -> Optional[IlerlemeDurumu]:
        """Mevcut ilerleme durumu."""
        return self._ilerleme

    # --------------------------------------------------------
    # Motor Otomatik Keşfi ve Kaydı
    # --------------------------------------------------------

    def otomatik_motor_kaydet(self) -> list[str]:
        """
        Kullanılabilir motorları otomatik algılar ve kaydeder.

        Her motor modülünü dinamik olarak import eder, kullanılabilirliğini
        kontrol eder ve ayarlarıyla birlikte kaydeder.

        Returns:
            Başarıyla kaydedilen motor adlarının listesi.
        """
        kaydedilenler: list[str] = []

        # Edge TTS (her zaman dene — ücretsiz, internetsiz çalışmaz ama yüklü olmalı)
        try:
            from engines.edge_engine import EdgeEngine
            motor_ayar = self._config.motor_ayar_al("edge_tts") or {}
            motor = EdgeEngine(motor_ayar)
            kullanilabilir, mesaj = EdgeEngine.kullanilabilir_mi()
            if kullanilabilir:
                self.motor_kaydet(motor)
                kaydedilenler.append("edge_tts")
            else:
                logger.info("Edge TTS kullanılamıyor: %s", mesaj)
        except ImportError:
            logger.debug("Edge TTS modülü bulunamadı.")

        # XTTS-v2
        try:
            from engines.xtts_engine import XTTSEngine
            motor_ayar = self._config.motor_ayar_al("xtts_v2") or {}
            if motor_ayar.get("aktif", False):
                motor = XTTSEngine(motor_ayar)
                kullanilabilir, mesaj = XTTSEngine.kullanilabilir_mi()
                if kullanilabilir:
                    self.motor_kaydet(motor)
                    kaydedilenler.append("xtts_v2")
                else:
                    logger.info("XTTS-v2 kullanılamıyor: %s", mesaj)
        except ImportError:
            logger.debug("XTTS-v2 modülü bulunamadı.")

        # OpenAI TTS
        try:
            from engines.openai_engine import OpenAIEngine
            motor_ayar = self._config.motor_ayar_al("openai") or {}
            if motor_ayar.get("aktif", False) and motor_ayar.get("api_key"):
                motor = OpenAIEngine(motor_ayar)
                kullanilabilir, mesaj = OpenAIEngine.kullanilabilir_mi()
                if kullanilabilir:
                    self.motor_kaydet(motor)
                    kaydedilenler.append("openai")
                else:
                    logger.info("OpenAI TTS kullanılamıyor: %s", mesaj)
        except ImportError:
            logger.debug("OpenAI modülü bulunamadı.")

        # ElevenLabs
        try:
            from engines.elevenlabs_engine import ElevenLabsEngine
            motor_ayar = self._config.motor_ayar_al("elevenlabs") or {}
            if motor_ayar.get("aktif", False) and motor_ayar.get("api_key"):
                motor = ElevenLabsEngine(motor_ayar)
                kullanilabilir, mesaj = ElevenLabsEngine.kullanilabilir_mi()
                if kullanilabilir:
                    self.motor_kaydet(motor)
                    kaydedilenler.append("elevenlabs")
                else:
                    logger.info("ElevenLabs kullanılamıyor: %s", mesaj)
        except ImportError:
            logger.debug("ElevenLabs modülü bulunamadı.")

        logger.info("Otomatik motor kaydı: %s", kaydedilenler)
        return kaydedilenler

    # --------------------------------------------------------
    # Temsil
    # --------------------------------------------------------

    def __repr__(self) -> str:
        kayitli = list(self._motorlar.keys())
        hazir = [ad for ad, m in self._motorlar.items() if m.hazir]
        return (
            f"<TTSManager kayıtlı={kayitli} hazır={hazir}>"
        )
