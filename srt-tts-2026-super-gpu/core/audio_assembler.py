# -*- coding: utf-8 -*-
"""
DubSync Pro — Ses Birleştirici (audio_assembler.py)

Üretilen ses segmentlerini altyazı zaman damgalarına göre tek bir
WAV dosyasında birleştirir. LUFS normalizasyon, fade-in/out ve
sessizlik doldurma işlemlerini uygular.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from core.srt_parser import AltyaziDosyasi, AltyaziSatiri
from core.timing_analyzer import ZamanlamaSonucu, ZamanlamaDurum
from core.time_stretcher import TimeStretcher
from engines.base_engine import SesUretimSonucu

logger = logging.getLogger("DubSync.AudioAssembler")


# ============================================================
# Veri Yapıları
# ============================================================

class BirlesimSonucu:
    """Birleştirme işleminin sonucunu tutar."""

    def __init__(self):
        self.basarili: bool = False
        self.dosya_yolu: str = ""
        self.toplam_sure_ms: int = 0
        self.ornekleme_hizi: int = 48000
        self.kanal: int = 1
        self.segment_sayisi: int = 0
        self.hizlandirilan: int = 0
        self.kirpilan: int = 0
        self.bos_birakilan: int = 0
        self.hata_mesaji: str = ""

    def ozet(self) -> str:
        """İnsan okunabilir özet."""
        sure_sn = self.toplam_sure_ms / 1000
        dk = int(sure_sn // 60)
        sn = sure_sn % 60
        return (
            f"Birleştirme: {self.segment_sayisi} segment, "
            f"süre: {dk}dk {sn:.1f}sn | "
            f"⚡ Hızl.: {self.hizlandirilan} | "
            f"✂️ Kırp.: {self.kirpilan} | "
            f"⬜ Boş: {self.bos_birakilan}"
        )


# ============================================================
# Ana Sınıf
# ============================================================

class AudioAssembler:
    """
    Ses segmentlerini altyazı zamanlamalarına göre birleştirir.

    İş akışı:
    1. Video süresi boyunca boş bir ses tamponu oluştur.
    2. Her segment için zamanlama analizine bak.
    3. Gerekirse hızlandır/yavaşlat/kırp.
    4. Segmenti doğru zaman pozisyonuna yerleştir.
    5. LUFS normalizasyonu uygula.
    6. WAV olarak kaydet.

    Kullanım:
        assembler = AudioAssembler(sr=48000)
        sonuc = assembler.birlesir(
            dosya, segmentler, zamanlama_sonuclari,
            cikis_yolu="output/dubbed.wav",
            video_sure_ms=6600000,
        )
    """

    def __init__(
        self,
        sr: int = 48000,
        bit_derinlik: int = 24,
        fade_in_ms: int = 30,
        fade_out_ms: int = 30,
        lufs_hedef: float = -24.0,
        normalize: bool = True,
    ):
        """
        Args:
            sr: Örnekleme hızı (Hz).
            bit_derinlik: Bit derinliği (16 veya 24).
            fade_in_ms: Her segment için fade-in süresi (ms).
            fade_out_ms: Her segment için fade-out süresi (ms).
            lufs_hedef: LUFS normalizasyon hedefi (-24.0 = yayın standardı).
            normalize: LUFS normalizasyonu uygulansın mı?
        """
        self._sr = sr
        self._bit_derinlik = bit_derinlik
        self._fade_in_ms = fade_in_ms
        self._fade_out_ms = fade_out_ms
        self._lufs_hedef = lufs_hedef
        self._normalize = normalize
        self._stretcher = TimeStretcher(motor="otomatik", hedef_sr=sr)

    @classmethod
    def ayarlardan_olustur(cls, config) -> "AudioAssembler":
        """ConfigManager'dan oluşturur."""
        return cls(
            sr=config.al("ses.ornekleme_hizi", 48000),
            bit_derinlik=config.al("ses.bit_derinlik", 24),
            fade_in_ms=config.al("zamanlama.fade_in_ms", 30),
            fade_out_ms=config.al("zamanlama.fade_out_ms", 30),
            lufs_hedef=config.al("ses.lufs_hedef", -24.0),
            normalize=config.al("ses.normalize", True),
        )

    # --------------------------------------------------------
    # Ana Birleştirme
    # --------------------------------------------------------

    def birlesir(
        self,
        dosya: AltyaziDosyasi,
        segmentler: dict[int, str],
        zamanlama_sonuclari: dict[int, ZamanlamaSonucu],
        cikis_yolu: str,
        video_sure_ms: Optional[int] = None,
        ilerleme_callback=None,
    ) -> BirlesimSonucu:
        """
        Tüm ses segmentlerini birleştirir.

        Args:
            dosya: AltyaziDosyasi nesnesi.
            segmentler: {satir_sira: ses_dosya_yolu} sözlüğü.
            zamanlama_sonuclari: {satir_sira: ZamanlamaSonucu} sözlüğü.
            cikis_yolu: Çıkış WAV dosya yolu.
            video_sure_ms: Video toplam süresi (ms). None ise son altyazıdan hesaplanır.
            ilerleme_callback: Her segment sonrası çağrılır (segment_no, toplam).

        Returns:
            BirlesimSonucu nesnesi.
        """
        sonuc = BirlesimSonucu()

        # Toplam süreyi belirle
        if video_sure_ms and video_sure_ms > 0:
            toplam_ms = video_sure_ms
        else:
            toplam_ms = dosya.toplam_sure_ms + 2000  # 2 sn tampon

        toplam_ornek = int(self._sr * toplam_ms / 1000)

        # Ana tampon: sessizlikle dolu
        tampon = np.zeros(toplam_ornek, dtype=np.float64)

        logger.info(
            "Birleştirme başlıyor: %d segment, tampon: %d örnek (%.1f sn)",
            len(segmentler), toplam_ornek, toplam_ms / 1000,
        )

        islenen = 0
        toplam_segment = len(dosya.satirlar)

        for satir in dosya.satirlar:
            sira = satir.sira

            # İlerleme bildir
            islenen += 1
            if ilerleme_callback:
                try:
                    ilerleme_callback(islenen, toplam_segment)
                except Exception:
                    pass

            # Segment dosyası var mı?
            segment_yolu = segmentler.get(sira)
            if not segment_yolu or not os.path.isfile(segment_yolu):
                sonuc.bos_birakilan += 1
                continue

            # Zamanlama sonucunu al
            zs = zamanlama_sonuclari.get(sira)
            if zs is None or zs.durum == ZamanlamaDurum.BOS:
                sonuc.bos_birakilan += 1
                continue

            # Ses verisini oku
            segment_verisi = self._segment_oku(segment_yolu)
            if segment_verisi is None:
                sonuc.bos_birakilan += 1
                continue

            # Zamanlama durumuna göre işle
            segment_verisi = self._zamanlama_isle(
                segment_verisi, satir, zs, sonuc
            )
            if segment_verisi is None:
                sonuc.bos_birakilan += 1
                continue

            # Fade uygula
            segment_verisi = self._fade_uygula(segment_verisi)

            # Tampona yerleştir
            self._tampona_yerlestir(tampon, segment_verisi, satir.baslangic_ms)
            sonuc.segment_sayisi += 1

        # LUFS normalizasyonu
        if self._normalize:
            tampon = self._lufs_normalize(tampon)

        # Dosyaya yaz
        try:
            Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)
            subtype = "PCM_24" if self._bit_derinlik == 24 else "PCM_16"
            sf.write(cikis_yolu, tampon, self._sr, subtype=subtype)

            sonuc.basarili = True
            sonuc.dosya_yolu = cikis_yolu
            sonuc.toplam_sure_ms = toplam_ms
            sonuc.ornekleme_hizi = self._sr
            sonuc.kanal = 1

            logger.info(sonuc.ozet())

        except Exception as e:
            sonuc.basarili = False
            sonuc.hata_mesaji = f"Dosya yazma hatası: {e}"
            logger.error(sonuc.hata_mesaji)

        return sonuc

    # --------------------------------------------------------
    # Segment Okuma
    # --------------------------------------------------------

    def _segment_oku(self, dosya_yolu: str) -> Optional[np.ndarray]:
        """
        Ses dosyasını numpy dizisi olarak okur.

        Farklı SR'leri hedef SR'ye resample eder, stereo'yu mono'ya çevirir.

        Returns:
            float64 numpy dizisi veya None.
        """
        try:
            y, sr = sf.read(dosya_yolu, dtype="float64")

            # Stereo → mono
            if y.ndim > 1:
                y = np.mean(y, axis=1)

            # Resample (gerekiyorsa)
            if sr != self._sr:
                try:
                    import librosa
                    y = librosa.resample(y, orig_sr=sr, target_sr=self._sr)
                except ImportError:
                    # librosa yoksa basit interpolasyon
                    oran = self._sr / sr
                    yeni_uzunluk = int(len(y) * oran)
                    x_eski = np.linspace(0, 1, len(y))
                    x_yeni = np.linspace(0, 1, yeni_uzunluk)
                    y = np.interp(x_yeni, x_eski, y)

            return y

        except Exception as e:
            logger.warning("Segment okunamadı (%s): %s", dosya_yolu, e)
            return None

    # --------------------------------------------------------
    # Zamanlama İşleme
    # --------------------------------------------------------

    def _zamanlama_isle(
        self,
        veri: np.ndarray,
        satir: AltyaziSatiri,
        zs: ZamanlamaSonucu,
        sonuc: BirlesimSonucu,
    ) -> Optional[np.ndarray]:
        """
        Zamanlama durumuna göre segmenti hızlandırır veya kırpar.
        Ses kısa kalırsa doğal hızında bırakılır (yavaşlatma yok).

        Returns:
            İşlenmiş numpy dizisi veya None.
        """
        slot_ornek = int(self._sr * satir.sure_ms / 1000)

        if zs.durum == ZamanlamaDurum.SIGIYOR:
            # Ses slota sığıyor — doğal hızda bırak
            return veri

        elif zs.durum in (ZamanlamaDurum.HAFIF_HIZLANDIR, ZamanlamaDurum.ORTA_HIZLANDIR):
            # Hızlandırma gerekli
            islenmis = self._bellek_stretch(veri, zs.hiz_orani)
            if islenmis is not None:
                sonuc.hizlandirilan += 1
                return islenmis
            # Stretch başarısız olursa kırp
            sonuc.kirpilan += 1
            return veri[:slot_ornek] if len(veri) > slot_ornek else veri

        elif zs.durum == ZamanlamaDurum.TASMA:
            # Taşma — maksimum hızda dene, yine sığmazsa kırp
            try:
                islenmis = self._bellek_stretch(veri, zs.hiz_orani)
                if islenmis is not None and len(islenmis) <= slot_ornek:
                    sonuc.hizlandirilan += 1
                    return islenmis
            except Exception:
                pass

            # Kırp
            sonuc.kirpilan += 1
            if len(veri) > slot_ornek:
                return veri[:slot_ornek]
            return veri

        return veri

    # --------------------------------------------------------
    # Bellekte Time Stretch
    # --------------------------------------------------------

    def _bellek_stretch(
        self, veri: np.ndarray, oran: float
    ) -> Optional[np.ndarray]:
        """
        Numpy dizisini bellekte time stretch eder.

        Args:
            veri: float64 ses dizisi.
            oran: Hız oranı (>1 = hızlandır).

        Returns:
            Stretch edilmiş numpy dizisi veya None.
        """
        if abs(oran - 1.0) < 0.01:
            return veri

        # Güvenlik sınırı
        oran = max(0.25, min(4.0, oran))

        # Önce pyrubberband dene
        try:
            import pyrubberband as pyrb
            return pyrb.time_stretch(veri, self._sr, oran)
        except (ImportError, Exception):
            pass

        # Librosa fallback
        try:
            import librosa
            return librosa.effects.time_stretch(veri, rate=oran)
        except Exception as e:
            logger.warning("Bellekte stretch başarısız (oran=%.2f): %s", oran, e)
            return None

    # --------------------------------------------------------
    # Fade Uygulama (Bellekte)
    # --------------------------------------------------------

    def _fade_uygula(self, veri: np.ndarray) -> np.ndarray:
        """Segmente fade-in ve fade-out uygular."""
        toplam = len(veri)

        if self._fade_in_ms > 0:
            fade_in_ornek = min(int(self._sr * self._fade_in_ms / 1000), toplam)
            if fade_in_ornek > 0:
                veri[:fade_in_ornek] *= np.linspace(0.0, 1.0, fade_in_ornek)

        if self._fade_out_ms > 0:
            fade_out_ornek = min(int(self._sr * self._fade_out_ms / 1000), toplam)
            if fade_out_ornek > 0:
                veri[-fade_out_ornek:] *= np.linspace(1.0, 0.0, fade_out_ornek)

        return veri

    # --------------------------------------------------------
    # Tampona Yerleştirme
    # --------------------------------------------------------

    def _tampona_yerlestir(
        self,
        tampon: np.ndarray,
        segment: np.ndarray,
        baslangic_ms: int,
    ) -> None:
        """
        Segmenti ana tamponda doğru pozisyona yerleştirir.

        Çakışma durumunda mevcut değerle toplanır (mix).

        Args:
            tampon: Ana ses tamponu.
            segment: Yerleştirilecek segment.
            baslangic_ms: Yerleştirme pozisyonu (ms).
        """
        baslangic_ornek = int(self._sr * baslangic_ms / 1000)
        bitis_ornek = baslangic_ornek + len(segment)

        # Tamponun sınırlarını aşmamak için kırp
        if baslangic_ornek >= len(tampon):
            return

        if bitis_ornek > len(tampon):
            fazla = bitis_ornek - len(tampon)
            segment = segment[:-fazla]
            bitis_ornek = len(tampon)

        # Mix: mevcut değerle topla (overlap durumunda)
        tampon[baslangic_ornek:bitis_ornek] += segment

    # --------------------------------------------------------
    # LUFS Normalizasyonu
    # --------------------------------------------------------

    def _lufs_normalize(self, veri: np.ndarray) -> np.ndarray:
        """
        Ses verisini hedef LUFS seviyesine normalize eder.

        Basitleştirilmiş LUFS yaklaşımı: RMS tabanlı normalizasyon.
        Tam ITU-R BS.1770 uyumlu LUFS için pyloudnorm kütüphanesi
        kullanılabilir (opsiyonel).

        Args:
            veri: Ses verisi (float64).

        Returns:
            Normalize edilmiş ses verisi.
        """
        # Önce pyloudnorm dene (daha doğru)
        try:
            import pyloudnorm as pyln
            meter = pyln.Meter(self._sr)
            mevcut_lufs = meter.integrated_loudness(veri)
            if np.isinf(mevcut_lufs) or np.isnan(mevcut_lufs):
                logger.warning("LUFS ölçülemedi (sessiz ses?), normalizasyon atlandı.")
                return veri
            veri = pyln.normalize.loudness(veri, mevcut_lufs, self._lufs_hedef)
            logger.debug(
                "LUFS normalizasyonu (pyloudnorm): %.1f → %.1f LUFS",
                mevcut_lufs, self._lufs_hedef,
            )
            return veri
        except ImportError:
            pass
        except Exception as e:
            logger.debug("pyloudnorm hatası: %s, RMS fallback kullanılıyor.", e)

        # Fallback: RMS tabanlı normalizasyon
        return self._rms_normalize(veri)

    def _rms_normalize(self, veri: np.ndarray) -> np.ndarray:
        """
        RMS tabanlı basit normalizasyon.

        LUFS'a yakın bir sonuç verir ama ITU-R BS.1770 standardına
        tam uyumlu değildir.
        """
        # Sessiz kısımları atla (eşik: -60 dBFS)
        esik = 10 ** (-60 / 20)
        aktif = veri[np.abs(veri) > esik]

        if len(aktif) == 0:
            logger.warning("Ses tamamen sessiz, normalizasyon atlandı.")
            return veri

        # Mevcut RMS'yi dB'ye çevir
        rms = np.sqrt(np.mean(aktif ** 2))
        if rms < 1e-10:
            return veri

        mevcut_db = 20 * np.log10(rms)

        # Hedef RMS (LUFS ≈ RMS yaklaşımı, ~0.5 dB fark)
        hedef_db = self._lufs_hedef

        # Kazanç
        kazanc_db = hedef_db - mevcut_db
        kazanc = 10 ** (kazanc_db / 20)

        veri = veri * kazanc

        # Clipping önleme (peak limiter)
        peak = np.max(np.abs(veri))
        if peak > 0.99:
            veri = veri * (0.99 / peak)

        logger.debug(
            "RMS normalizasyonu: mevcut=%.1f dB, hedef=%.1f dB, kazanç=%.1f dB",
            mevcut_db, hedef_db, kazanc_db,
        )
        return veri

    # --------------------------------------------------------
    # Tek Segment Birleştirme Yardımcısı
    # --------------------------------------------------------

    def segment_isle_ve_kaydet(
        self,
        girdi_yolu: str,
        cikti_yolu: str,
        zs: ZamanlamaSonucu,
    ) -> bool:
        """
        Tek bir segmenti zamanlama sonucuna göre işler ve kaydeder.

        Önizleme (preview) için kullanılır.

        Args:
            girdi_yolu: Orijinal segment dosyası.
            cikti_yolu: İşlenmiş çıkış dosyası.
            zs: ZamanlamaSonucu nesnesi.

        Returns:
            True: başarılı.
        """
        veri = self._segment_oku(girdi_yolu)
        if veri is None:
            return False

        # Geçici sonuc nesnesi (istatistik için)
        tmp_sonuc = BirlesimSonucu()

        # Geçici AltyaziSatiri (zamanlama_isle için)
        from core.srt_parser import AltyaziSatiri
        tmp_satir = AltyaziSatiri(
            sira=zs.satir_sira,
            baslangic_ms=0,
            bitis_ms=zs.slot_ms,
            ham_metin="",
            temiz_metin="",
        )

        islenmis = self._zamanlama_isle(veri, tmp_satir, zs, tmp_sonuc)
        if islenmis is None:
            return False

        islenmis = self._fade_uygula(islenmis)

        try:
            Path(cikti_yolu).parent.mkdir(parents=True, exist_ok=True)
            subtype = "PCM_24" if self._bit_derinlik == 24 else "PCM_16"
            sf.write(cikti_yolu, islenmis, self._sr, subtype=subtype)
            return True
        except Exception as e:
            logger.error("Segment kaydetme hatası: %s", e)
            return False

    # --------------------------------------------------------
    # Bilgi
    # --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<AudioAssembler sr={self._sr} bit={self._bit_derinlik} "
            f"fade_in={self._fade_in_ms}ms fade_out={self._fade_out_ms}ms "
            f"lufs={self._lufs_hedef}>"
        )
