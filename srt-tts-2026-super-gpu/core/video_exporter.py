# -*- coding: utf-8 -*-
"""
DubSync Pro — Video Çıkış (video_exporter.py)

FFmpeg ile orijinal videoyu seslendirme sesiyle birleştirir.
Video codec'i kopyalar (yeniden encode yok = kalite kaybı yok),
ses codec'i ayarlanabilir (AAC, FLAC, PCM).
"""

import logging
import os
import subprocess
import shutil
import json
import re
import threading
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("DubSync.VideoExporter")


# ============================================================
# Sonuç Sınıfı
# ============================================================

class ExportSonucu:
    """Video export işleminin sonucunu tutar."""

    def __init__(self):
        self.basarili: bool = False
        self.dosya_yolu: str = ""
        self.dosya_boyutu_mb: float = 0.0
        self.video_sure_ms: int = 0
        self.hata_mesaji: str = ""

    def ozet(self) -> str:
        if self.basarili:
            return (
                f"Export başarılı: {self.dosya_yolu} "
                f"({self.dosya_boyutu_mb:.1f} MB)"
            )
        return f"Export başarısız: {self.hata_mesaji}"

    def __repr__(self) -> str:
        durum = "başarılı" if self.basarili else "başarısız"
        return f"<ExportSonucu {durum}>"


# ============================================================
# Video Bilgisi
# ============================================================

class VideoBilgisi:
    """FFprobe ile alınan video bilgilerini tutar."""

    def __init__(self):
        self.sure_ms: int = 0
        self.genislik: int = 0
        self.yukseklik: int = 0
        self.fps: float = 0.0
        self.video_codec: str = ""
        self.ses_codec: str = ""
        self.ses_kanal: int = 0
        self.ses_sr: int = 0
        self.dosya_boyutu_mb: float = 0.0
        self.format: str = ""

    def __repr__(self) -> str:
        return (
            f"<Video {self.genislik}x{self.yukseklik} "
            f"{self.fps:.1f}fps {self.video_codec} "
            f"ses={self.ses_codec} {self.ses_sr}Hz "
            f"süre={self.sure_ms / 1000:.1f}s>"
        )


# ============================================================
# Ana Sınıf
# ============================================================

class VideoExporter:
    """
    FFmpeg ile video export işlemlerini yönetir.

    İşlevler:
    - Video bilgisi sorgulama (süre, codec, çözünürlük).
    - Orijinal video + yeni ses → MP4/MKV birleştirme.
    - Video codec kopyalama (kalite kaybı yok).
    - Ses codec seçimi (AAC, FLAC, PCM).
    - Sadece ses çıkışı (WAV/MP3/AAC).
    """

    def __init__(
        self,
        video_codec: str = "copy",
        ses_codec: str = "aac",
        ses_bitrate: str = "320k",
        cikis_format: str = "mp4",
        dosya_son_eki: str = "_dubbed",
        uzerine_yaz: bool = False,
    ):
        """
        Args:
            video_codec: Video codec ("copy" = yeniden encode yok).
            ses_codec: Ses codec ("aac", "flac", "pcm_s24le").
            ses_bitrate: AAC bitrate (örn: "320k", "256k").
            cikis_format: Çıkış formatı ("mp4", "mkv").
            dosya_son_eki: Çıkış dosya adına eklenen son ek.
            uzerine_yaz: Mevcut dosyanın üzerine yazılsın mı?
        """
        self._video_codec = video_codec
        self._ses_codec = ses_codec
        self._ses_bitrate = ses_bitrate
        self._cikis_format = cikis_format
        self._dosya_son_eki = dosya_son_eki
        self._uzerine_yaz = uzerine_yaz

    @classmethod
    def ayarlardan_olustur(cls, config) -> "VideoExporter":
        """ConfigManager'dan oluşturur."""
        return cls(
            video_codec=config.al("cikis.video_codec", "copy"),
            ses_codec=config.al("cikis.ses_codec", "aac"),
            ses_bitrate=config.al("cikis.ses_bitrate", "320k"),
            cikis_format=config.al("cikis.format", "mp4"),
            dosya_son_eki=config.al("cikis.dosya_son_eki", "_dubbed"),
            uzerine_yaz=config.al("cikis.uzerine_yaz", False),
        )

    # --------------------------------------------------------
    # FFmpeg / FFprobe Kontrol
    # --------------------------------------------------------

    @staticmethod
    def ffmpeg_mevcut() -> bool:
        """FFmpeg'in PATH'te olup olmadığını kontrol eder."""
        return shutil.which("ffmpeg") is not None

    @staticmethod
    def ffprobe_mevcut() -> bool:
        """FFprobe'un PATH'te olup olmadığını kontrol eder."""
        return shutil.which("ffprobe") is not None

    # --------------------------------------------------------
    # Video Bilgisi
    # --------------------------------------------------------

    @staticmethod
    def video_bilgisi_al(video_yolu: str) -> Optional[VideoBilgisi]:
        """
        FFprobe ile video dosyasının bilgilerini alır.

        Args:
            video_yolu: Video dosya yolu.

        Returns:
            VideoBilgisi nesnesi veya None.
        """
        if not os.path.isfile(video_yolu):
            logger.error("Video bulunamadı: %s", video_yolu)
            return None

        if not shutil.which("ffprobe"):
            logger.error("ffprobe bulunamadı.")
            return None

        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_yolu,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)

            if proc.returncode != 0:
                logger.error("ffprobe hatası: %s", proc.stderr.decode(errors="replace")[:200])
                return None

            veri = json.loads(proc.stdout.decode("utf-8"))

        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            logger.error("Video bilgisi alınamadı: %s", e)
            return None

        bilgi = VideoBilgisi()

        # Format bilgisi
        fmt = veri.get("format", {})
        sure_sn = float(fmt.get("duration", 0))
        bilgi.sure_ms = int(sure_sn * 1000)
        bilgi.dosya_boyutu_mb = int(fmt.get("size", 0)) / (1024 * 1024)
        bilgi.format = fmt.get("format_name", "")

        # Stream bilgileri
        for stream in veri.get("streams", []):
            codec_type = stream.get("codec_type", "")

            if codec_type == "video" and not bilgi.video_codec:
                bilgi.video_codec = stream.get("codec_name", "")
                bilgi.genislik = int(stream.get("width", 0))
                bilgi.yukseklik = int(stream.get("height", 0))

                # FPS hesapla
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_str.split("/")
                    bilgi.fps = float(num) / float(den) if float(den) > 0 else 0
                except (ValueError, ZeroDivisionError):
                    bilgi.fps = 0

            elif codec_type == "audio" and not bilgi.ses_codec:
                bilgi.ses_codec = stream.get("codec_name", "")
                bilgi.ses_kanal = int(stream.get("channels", 0))
                bilgi.ses_sr = int(stream.get("sample_rate", 0))

        logger.info("Video bilgisi: %s", repr(bilgi))
        return bilgi

    @staticmethod
    def video_suresi_al(video_yolu: str) -> int:
        """
        Video süresini milisaniye olarak döndürür.

        Args:
            video_yolu: Video dosya yolu.

        Returns:
            Süre (ms). Hata durumunda 0.
        """
        bilgi = VideoExporter.video_bilgisi_al(video_yolu)
        if bilgi:
            return bilgi.sure_ms
        return 0

    # --------------------------------------------------------
    # Video + Ses Birleştirme
    # --------------------------------------------------------

    def export(
        self,
        video_yolu: str,
        ses_yolu: str,
        cikis_yolu: Optional[str] = None,
        ilerleme_callback: Optional[Callable[[float], None]] = None,
    ) -> ExportSonucu:
        """
        Orijinal video ile yeni ses dosyasını birleştirir.

        Video codec kopyalanır (yeniden encode yok).
        Orijinal ses kanalı yeni sesle değiştirilir.

        Args:
            video_yolu: Orijinal video dosya yolu.
            ses_yolu: Yeni ses dosya yolu (WAV veya diğer).
            cikis_yolu: Çıkış dosya yolu. None ise otomatik oluşturulur.
            ilerleme_callback: İlerleme fonksiyonu (yüzde: float 0-100).

        Returns:
            ExportSonucu nesnesi.
        """
        sonuc = ExportSonucu()

        # Kontroller
        if not os.path.isfile(video_yolu):
            sonuc.hata_mesaji = f"Video bulunamadı: {video_yolu}"
            return sonuc

        if not os.path.isfile(ses_yolu):
            sonuc.hata_mesaji = f"Ses dosyası bulunamadı: {ses_yolu}"
            return sonuc

        if not self.ffmpeg_mevcut():
            sonuc.hata_mesaji = (
                "FFmpeg bulunamadı. Kurulum:\n"
                "  Windows: winget install ffmpeg\n"
                "  Linux: sudo apt install ffmpeg\n"
                "  macOS: brew install ffmpeg"
            )
            return sonuc

        # Çıkış yolunu oluştur
        if cikis_yolu is None:
            cikis_yolu = self._cikis_yolu_olustur(video_yolu)

        # Üzerine yazma kontrolü
        if os.path.isfile(cikis_yolu) and not self._uzerine_yaz:
            # Dosya adını numaralandır
            cikis_yolu = self._benzersiz_yol(cikis_yolu)

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        # Video süresini al (ilerleme hesabı için)
        video_suresi_ms = self.video_suresi_al(video_yolu)

        # FFmpeg komutu
        cmd = self._ffmpeg_komutu_olustur(video_yolu, ses_yolu, cikis_yolu)

        logger.info("Export başlıyor: %s", " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )

            # [DÜZELTİLDİ] stderr'den ilerleme oku (FFmpeg progress bilgisi)
            stderr_satirlar = []

            def _stderr_oku():
                """stderr'i thread'de oku ve ilerleme callback'i çağır."""
                for satir in proc.stderr:
                    stderr_satirlar.append(satir)
                    if ilerleme_callback and video_suresi_ms > 0:
                        # FFmpeg "time=HH:MM:SS.mm" formatında ilerleme verir
                        eslesme = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", satir)
                        if eslesme:
                            try:
                                saat = int(eslesme.group(1))
                                dakika = int(eslesme.group(2))
                                saniye = int(eslesme.group(3))
                                gecen_ms = (saat * 3600 + dakika * 60 + saniye) * 1000
                                yuzde = min(99.0, (gecen_ms / video_suresi_ms) * 100)
                                ilerleme_callback(yuzde)
                            except (ValueError, ZeroDivisionError):
                                pass

            stderr_thread = threading.Thread(target=_stderr_oku, daemon=True)
            stderr_thread.start()

            # Stdout'u boşalt (genellikle boş)
            proc.stdout.read()

            # Süreç bitişini bekle
            proc.wait(timeout=1800)  # 30 dk timeout
            stderr_thread.join(timeout=5)

            if proc.returncode == 0 and os.path.isfile(cikis_yolu):
                boyut = os.path.getsize(cikis_yolu) / (1024 * 1024)
                sonuc.basarili = True
                sonuc.dosya_yolu = cikis_yolu
                sonuc.dosya_boyutu_mb = boyut

                # Süreyi al
                bilgi = self.video_bilgisi_al(cikis_yolu)
                if bilgi:
                    sonuc.video_sure_ms = bilgi.sure_ms

                # [DÜZELTİLDİ] Tamamlandı — %100 bildir
                if ilerleme_callback:
                    ilerleme_callback(100.0)

                logger.info(sonuc.ozet())
            else:
                hata = "".join(stderr_satirlar)[-500:]
                sonuc.hata_mesaji = f"FFmpeg hatası (kod {proc.returncode}): {hata}"
                logger.error(sonuc.hata_mesaji[:200])

        except subprocess.TimeoutExpired:
            proc.kill()
            sonuc.hata_mesaji = "FFmpeg zaman aşımı (30 dakika)."
            logger.error(sonuc.hata_mesaji)
        except FileNotFoundError:
            sonuc.hata_mesaji = "FFmpeg bulunamadı."
        except Exception as e:
            sonuc.hata_mesaji = f"Export hatası: {e}"
            logger.error(sonuc.hata_mesaji)

        return sonuc

    def _ffmpeg_komutu_olustur(
        self,
        video_yolu: str,
        ses_yolu: str,
        cikis_yolu: str,
    ) -> list[str]:
        """FFmpeg komut satırını oluşturur."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_yolu,           # Girdi 1: orijinal video
            "-i", ses_yolu,             # Girdi 2: yeni ses
            "-map", "0:v",              # Video: orijinalden al
            "-map", "1:a",              # Ses: yeni dosyadan al
        ]

        # Video codec
        cmd.extend(["-c:v", self._video_codec])

        # Ses codec
        if self._ses_codec == "aac":
            cmd.extend([
                "-c:a", "aac",
                "-b:a", self._ses_bitrate,
            ])
        elif self._ses_codec == "flac":
            cmd.extend(["-c:a", "flac"])
        elif self._ses_codec in ("pcm_s24le", "pcm_s16le"):
            cmd.extend(["-c:a", self._ses_codec])
        elif self._ses_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "320k"])

        # İlerleme bilgisi için stats_period ekle
        cmd.extend(["-stats_period", "0.5"])

        # Çıkış
        cmd.append(cikis_yolu)

        return cmd

    # --------------------------------------------------------
    # Sadece Ses Çıkışı
    # --------------------------------------------------------

    def sadece_ses_export(
        self,
        ses_yolu: str,
        cikis_yolu: str,
        cikis_format: str = "wav",
    ) -> ExportSonucu:
        """
        Ses dosyasını istenen formata dönüştürerek kaydeder.

        Args:
            ses_yolu: Kaynak ses dosyası.
            cikis_yolu: Çıkış dosya yolu.
            cikis_format: "wav", "mp3", "aac", "flac".

        Returns:
            ExportSonucu nesnesi.
        """
        sonuc = ExportSonucu()

        if not os.path.isfile(ses_yolu):
            sonuc.hata_mesaji = f"Ses dosyası bulunamadı: {ses_yolu}"
            return sonuc

        Path(cikis_yolu).parent.mkdir(parents=True, exist_ok=True)

        # WAV ise doğrudan kopyala (FFmpeg gerekmez)
        if cikis_format == "wav" and ses_yolu.lower().endswith(".wav"):
            try:
                shutil.copy2(ses_yolu, cikis_yolu)
                sonuc.basarili = True
                sonuc.dosya_yolu = cikis_yolu
                sonuc.dosya_boyutu_mb = os.path.getsize(cikis_yolu) / (1024 * 1024)
                return sonuc
            except OSError as e:
                sonuc.hata_mesaji = f"Kopyalama hatası: {e}"
                return sonuc

        if not self.ffmpeg_mevcut():
            sonuc.hata_mesaji = "FFmpeg bulunamadı."
            return sonuc

        # FFmpeg ile dönüştür
        codec_map = {
            "wav": ["-acodec", "pcm_s24le"],
            "mp3": ["-acodec", "libmp3lame", "-b:a", "320k"],
            "aac": ["-acodec", "aac", "-b:a", "320k"],
            "flac": ["-acodec", "flac"],
        }
        codec_args = codec_map.get(cikis_format, ["-acodec", "pcm_s24le"])

        cmd = [
            "ffmpeg", "-y",
            "-i", ses_yolu,
            *codec_args,
            cikis_yolu,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120)

            if proc.returncode == 0 and os.path.isfile(cikis_yolu):
                sonuc.basarili = True
                sonuc.dosya_yolu = cikis_yolu
                sonuc.dosya_boyutu_mb = os.path.getsize(cikis_yolu) / (1024 * 1024)
            else:
                hata = proc.stderr.decode(errors="replace")[-200:]
                sonuc.hata_mesaji = f"FFmpeg dönüşüm hatası: {hata}"

        except Exception as e:
            sonuc.hata_mesaji = f"Ses dönüşüm hatası: {e}"

        return sonuc

    # --------------------------------------------------------
    # Orijinal Ses + TTS → Video (Tek Adım)
    # --------------------------------------------------------

    def export_ducked(
        self,
        video_yolu: str,
        mikslenmis_ses_yolu: str,
        cikis_yolu: Optional[str] = None,
    ) -> ExportSonucu:
        """
        Video + ducking uygulanmış mikslenen sesi birleştirir.

        AudioDucker'ın çıkışını doğrudan video ile birleştirir.
        Bu, export() ile aynı işlevi görür — kolaylık metodu.

        Args:
            video_yolu: Orijinal video.
            mikslenmis_ses_yolu: Ducking+TTS mikslenen ses.
            cikis_yolu: Çıkış yolu.

        Returns:
            ExportSonucu.
        """
        return self.export(video_yolu, mikslenmis_ses_yolu, cikis_yolu)

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    def _cikis_yolu_olustur(self, video_yolu: str) -> str:
        """
        Video yolundan otomatik çıkış yolu oluşturur.

        Örnek:
            "film.mp4" → "film_dubbed.mp4"
            "/path/film.mkv" → "/path/film_dubbed.mkv"
        """
        yol = Path(video_yolu)
        ad = yol.stem  # Uzantısız dosya adı
        uzanti = f".{self._cikis_format}"
        yeni_ad = f"{ad}{self._dosya_son_eki}{uzanti}"
        return str(yol.parent / yeni_ad)

    @staticmethod
    def _benzersiz_yol(dosya_yolu: str) -> str:
        """
        Mevcut dosya varsa numaralandırarak benzersiz yol oluşturur.

        Örnek:
            "film_dubbed.mp4" → "film_dubbed_2.mp4" → "film_dubbed_3.mp4"
        """
        if not os.path.exists(dosya_yolu):
            return dosya_yolu

        yol = Path(dosya_yolu)
        ad = yol.stem
        uzanti = yol.suffix
        dizin = yol.parent

        sayac = 2
        while True:
            yeni_yol = str(dizin / f"{ad}_{sayac}{uzanti}")
            if not os.path.exists(yeni_yol):
                return yeni_yol
            sayac += 1
            if sayac > 999:
                return str(dizin / f"{ad}_son{uzanti}")

    def __repr__(self) -> str:
        return (
            f"<VideoExporter v_codec={self._video_codec} "
            f"a_codec={self._ses_codec} "
            f"bitrate={self._ses_bitrate} "
            f"format={self._cikis_format}>"
        )
