# -*- coding: utf-8 -*-
"""
DubSync Pro — Zamanlama Analizörü (timing_analyzer.py)

Üretilen ses süresini altyazı zaman slotuna karşı ölçer,
hızlandırma kararı verir ve çakışma tespiti yapar.
Ses kısa kalırsa yavaşlatılmaz, doğal hızında bırakılır.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.srt_parser import AltyaziSatiri, AltyaziDosyasi
from engines.base_engine import SesUretimSonucu

logger = logging.getLogger("DubSync.TimingAnalyzer")


# ============================================================
# Veri Yapıları
# ============================================================

class ZamanlamaDurum(Enum):
    """Bir altyazı satırının zamanlama durumu."""
    SIGIYOR = "sigiyor"                 # Ses ≤ slot, sessizlikle doldurulur (doğal hız)
    HAFIF_HIZLANDIR = "hafif_hizlandir" # Ses > slot ama oran ≤ %150
    ORTA_HIZLANDIR = "orta_hizlandir"   # %150 < oran ≤ max_hiz_orani
    TASMA = "tasma"                     # Oran > max_hiz_orani, sorunlu
    BOS = "bos"                         # Ses üretimi başarısız veya boş


@dataclass
class ZamanlamaSonucu:
    """Tek bir altyazı satırının zamanlama analiz sonucu."""

    satir_sira: int                     # Altyazı sıra numarası
    slot_ms: int                        # Altyazı zaman slotu (bitiş - başlangıç)
    ses_ms: int                         # Üretilen sesin süresi
    durum: ZamanlamaDurum               # Zamanlama durumu
    hiz_orani: float = 1.0             # Gereken hız oranı (1.0 = normal)
    hedef_ms: int = 0                   # Hedef süre (hızlandırma sonrası)
    sessizlik_ms: int = 0               # Eklenecek sessizlik (ms)
    uyari: str = ""                     # Varsa uyarı mesajı

    @property
    def sorunlu(self) -> bool:
        """Taşma durumunda mı?"""
        return self.durum == ZamanlamaDurum.TASMA

    @property
    def hizlandirma_gerekli(self) -> bool:
        """Hızlandırma gerekli mi?"""
        return self.durum in (
            ZamanlamaDurum.HAFIF_HIZLANDIR,
            ZamanlamaDurum.ORTA_HIZLANDIR,
        )


@dataclass
class AnalizRaporu:
    """Tüm altyazı dosyasının zamanlama analiz raporu."""

    sonuclar: list[ZamanlamaSonucu] = field(default_factory=list)
    toplam_satir: int = 0
    sigiyor: int = 0
    hafif_hizlandir: int = 0
    orta_hizlandir: int = 0
    tasma: int = 0
    bos: int = 0
    cakisma_sayisi: int = 0             # Ardışık altyazıların çakıştığı yer sayısı
    ortalama_hiz_orani: float = 1.0
    max_hiz_orani_gerekli: float = 1.0

    @property
    def sorunlu_satir_sayisi(self) -> int:
        return self.tasma

    @property
    def basari_yuzdesi(self) -> float:
        """Sorunsuz satır yüzdesi."""
        if self.toplam_satir == 0:
            return 0.0
        sorunsuz = self.toplam_satir - self.tasma - self.bos
        return (sorunsuz / self.toplam_satir) * 100.0

    def ozet(self) -> str:
        """İnsan okunabilir özet."""
        return (
            f"Analiz: {self.toplam_satir} satır | "
            f"✅ Sığıyor: {self.sigiyor} | "
            f"⚡ Hafif hızl.: {self.hafif_hizlandir} | "
            f"⚡⚡ Orta hızl.: {self.orta_hizlandir} | "
            f"❌ Taşma: {self.tasma} | "
            f"⬜ Boş: {self.bos} | "
            f"🔀 Çakışma: {self.cakisma_sayisi} | "
            f"Max hız: {self.max_hiz_orani_gerekli:.2f}x | "
            f"Başarı: %{self.basari_yuzdesi:.1f}"
        )


# ============================================================
# Zamanlama Analizörü
# ============================================================

class TimingAnalyzer:
    """
    Ses süresi ile altyazı zaman slotunu karşılaştırır.

    Her satır için:
    - Hızlandırma oranını hesaplar.
    - Durumu belirler (sığıyor/hızlandır/taşma).
    - Ses kısa kalırsa yavaşlatmaz, doğal hızında bırakır.
    - Ardışık çakışmaları tespit eder.
    - Toplam rapor üretir.

    Kullanım:
        analyzer = TimingAnalyzer(max_hiz_orani=2.0)
        sonuc = analyzer.satir_analiz(satir, ses_ms=3500)
        rapor = analyzer.toplu_analiz(dosya, ses_sureleri)
    """

    def __init__(
        self,
        max_hiz_orani: float = 2.0,
        min_sessizlik_ms: int = 50,
        fade_in_ms: int = 30,
        fade_out_ms: int = 30,
        on_bosluk_ms: int = 0,
        son_bosluk_ms: int = 0,
    ):
        """
        Args:
            max_hiz_orani: Maksimum hızlandırma oranı (2.0 = %200).
            min_sessizlik_ms: Minimum eklenecek sessizlik (ms).
            fade_in_ms: Fade-in süresi (ms).
            fade_out_ms: Fade-out süresi (ms).
            on_bosluk_ms: Seslendirme öncesi ek boşluk (ms).
            son_bosluk_ms: Seslendirme sonrası ek boşluk (ms).
        """
        self.max_hiz_orani = max(1.0, max_hiz_orani)
        self.min_sessizlik_ms = max(0, min_sessizlik_ms)
        self.fade_in_ms = max(0, fade_in_ms)
        self.fade_out_ms = max(0, fade_out_ms)
        self.on_bosluk_ms = max(0, on_bosluk_ms)
        self.son_bosluk_ms = max(0, son_bosluk_ms)

    @classmethod
    def ayarlardan_olustur(cls, config) -> "TimingAnalyzer":
        """
        ConfigManager'dan ayarları okuyarak oluşturur.

        Args:
            config: ConfigManager nesnesi.

        Returns:
            TimingAnalyzer nesnesi.
        """
        return cls(
            max_hiz_orani=config.al("zamanlama.max_hiz_orani", 2.0),
            min_sessizlik_ms=config.al("zamanlama.min_sessizlik_ms", 50),
            fade_in_ms=config.al("zamanlama.fade_in_ms", 30),
            fade_out_ms=config.al("zamanlama.fade_out_ms", 30),
            on_bosluk_ms=config.al("zamanlama.on_bosluk_ms", 0),
            son_bosluk_ms=config.al("zamanlama.son_bosluk_ms", 0),
        )

    # --------------------------------------------------------
    # Tekil Satır Analizi
    # --------------------------------------------------------

    def satir_analiz(
        self,
        satir: AltyaziSatiri,
        ses_ms: int,
    ) -> ZamanlamaSonucu:
        """
        Tek bir altyazı satırının zamanlama analizini yapar.

        Args:
            satir: AltyaziSatiri nesnesi.
            ses_ms: Üretilen sesin süresi (milisaniye).

        Returns:
            ZamanlamaSonucu nesnesi.
        """
        slot_ms = satir.sure_ms

        # Slot'tan boşlukları çıkar (efektif kullanılabilir süre)
        efektif_slot = max(
            0,
            slot_ms - self.on_bosluk_ms - self.son_bosluk_ms
        )

        # Ses üretimi başarısız veya 0 süreli
        if ses_ms <= 0:
            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=0,
                durum=ZamanlamaDurum.BOS,
                uyari="Ses üretimi başarısız veya boş.",
            )

        # Efektif slot çok küçükse (< 100ms)
        if efektif_slot < 100:
            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=ses_ms,
                durum=ZamanlamaDurum.TASMA,
                hiz_orani=ses_ms / max(efektif_slot, 1),
                uyari=f"Altyazı slotu çok kısa: {slot_ms}ms",
            )

        # Hız oranı: ses_ms / efektif_slot
        # >1 = ses slottan uzun (hızlandır), <1 = ses slottan kısa (doğal hızda bırak)
        hiz_orani = ses_ms / efektif_slot

        # --- Durum belirleme ---

        if hiz_orani <= 1.0:
            # Ses slota sığıyor — doğal hızda bırak, kalan kısım sessizlik
            sessizlik = efektif_slot - ses_ms

            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=ses_ms,
                durum=ZamanlamaDurum.SIGIYOR,
                hiz_orani=1.0,
                hedef_ms=ses_ms,
                sessizlik_ms=max(0, sessizlik),
            )

        elif hiz_orani <= 1.5:
            # Hafif hızlandırma (%100-%150 arası) — kalite kaybı minimal
            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=ses_ms,
                durum=ZamanlamaDurum.HAFIF_HIZLANDIR,
                hiz_orani=hiz_orani,
                hedef_ms=efektif_slot,
                uyari=f"Hafif hızlandırma: {hiz_orani:.2f}x",
            )

        elif hiz_orani <= self.max_hiz_orani:
            # Orta hızlandırma (%150 - max) — algılanabilir hızlanma
            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=ses_ms,
                durum=ZamanlamaDurum.ORTA_HIZLANDIR,
                hiz_orani=hiz_orani,
                hedef_ms=efektif_slot,
                uyari=f"Orta hızlandırma: {hiz_orani:.2f}x",
            )

        else:
            # Taşma — max hız bile yetmiyor
            return ZamanlamaSonucu(
                satir_sira=satir.sira,
                slot_ms=slot_ms,
                ses_ms=ses_ms,
                durum=ZamanlamaDurum.TASMA,
                hiz_orani=hiz_orani,
                hedef_ms=efektif_slot,
                uyari=(
                    f"Taşma! Oran {hiz_orani:.2f}x > max {self.max_hiz_orani:.1f}x. "
                    f"Ses {ses_ms}ms, slot {efektif_slot}ms."
                ),
            )

    # --------------------------------------------------------
    # Toplu Analiz
    # --------------------------------------------------------

    def toplu_analiz(
        self,
        dosya: AltyaziDosyasi,
        ses_sureleri: dict[int, int],
    ) -> AnalizRaporu:
        """
        Tüm altyazı dosyasını analiz eder.

        Args:
            dosya: AltyaziDosyasi nesnesi.
            ses_sureleri: {satir_sira: ses_suresi_ms} sözlüğü.
                          Eksik satırlar için 0 varsayılır.

        Returns:
            AnalizRaporu nesnesi.
        """
        rapor = AnalizRaporu()
        rapor.toplam_satir = dosya.satir_sayisi

        hiz_oranlari: list[float] = []
        max_hiz: float = 1.0

        for satir in dosya.satirlar:
            ses_ms = ses_sureleri.get(satir.sira, 0)
            sonuc = self.satir_analiz(satir, ses_ms)
            rapor.sonuclar.append(sonuc)

            # İstatistik güncelle
            if sonuc.durum == ZamanlamaDurum.SIGIYOR:
                rapor.sigiyor += 1
            elif sonuc.durum == ZamanlamaDurum.HAFIF_HIZLANDIR:
                rapor.hafif_hizlandir += 1
            elif sonuc.durum == ZamanlamaDurum.ORTA_HIZLANDIR:
                rapor.orta_hizlandir += 1
            elif sonuc.durum == ZamanlamaDurum.TASMA:
                rapor.tasma += 1
            elif sonuc.durum == ZamanlamaDurum.BOS:
                rapor.bos += 1

            if sonuc.hiz_orani > 0:
                hiz_oranlari.append(sonuc.hiz_orani)
            if sonuc.hiz_orani > max_hiz:
                max_hiz = sonuc.hiz_orani

        # Çakışma tespiti
        rapor.cakisma_sayisi = self._cakisma_tespit(dosya)

        # Ortalama ve max hız oranları
        if hiz_oranlari:
            rapor.ortalama_hiz_orani = sum(hiz_oranlari) / len(hiz_oranlari)
        rapor.max_hiz_orani_gerekli = max_hiz

        logger.info(rapor.ozet())
        return rapor

    # --------------------------------------------------------
    # Çakışma Tespiti
    # --------------------------------------------------------

    @staticmethod
    def _cakisma_tespit(dosya: AltyaziDosyasi) -> int:
        """
        Ardışık altyazıların zaman olarak çakışıp çakışmadığını kontrol eder.

        İki altyazı çakışır eğer birincinin bitiş zamanı ikincinin
        başlangıç zamanından büyükse.

        Args:
            dosya: AltyaziDosyasi nesnesi.

        Returns:
            Çakışma sayısı.
        """
        cakisma = 0
        satirlar = dosya.satirlar

        for i in range(len(satirlar) - 1):
            mevcut = satirlar[i]
            sonraki = satirlar[i + 1]

            if mevcut.bitis_ms > sonraki.baslangic_ms:
                cakisma += 1
                logger.debug(
                    "Çakışma: Satır %d (bitiş %dms) > Satır %d (başlangıç %dms), "
                    "çakışma: %dms",
                    mevcut.sira,
                    mevcut.bitis_ms,
                    sonraki.sira,
                    sonraki.baslangic_ms,
                    mevcut.bitis_ms - sonraki.baslangic_ms,
                )

        return cakisma

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @staticmethod
    def durum_renk(durum: ZamanlamaDurum) -> str:
        """
        GUI'de kullanılacak renk kodunu döndürür.

        Returns:
            Hex renk kodu.
        """
        renk_map = {
            ZamanlamaDurum.SIGIYOR: "#4CAF50",          # Yeşil
            ZamanlamaDurum.HAFIF_HIZLANDIR: "#FFC107",   # Sarı
            ZamanlamaDurum.ORTA_HIZLANDIR: "#FF9800",    # Turuncu
            ZamanlamaDurum.TASMA: "#F44336",             # Kırmızı
            ZamanlamaDurum.BOS: "#9E9E9E",               # Gri
        }
        return renk_map.get(durum, "#9E9E9E")

    @staticmethod
    def durum_ikon(durum: ZamanlamaDurum) -> str:
        """
        GUI'de kullanılacak durum ikonunu döndürür.

        Returns:
            Emoji/unicode ikon.
        """
        ikon_map = {
            ZamanlamaDurum.SIGIYOR: "✅",
            ZamanlamaDurum.HAFIF_HIZLANDIR: "⚡",
            ZamanlamaDurum.ORTA_HIZLANDIR: "⚡⚡",
            ZamanlamaDurum.TASMA: "❌",
            ZamanlamaDurum.BOS: "⬜",
        }
        return ikon_map.get(durum, "❓")

    def __repr__(self) -> str:
        return (
            f"<TimingAnalyzer max_hız={self.max_hiz_orani:.1f}x>"
        )
