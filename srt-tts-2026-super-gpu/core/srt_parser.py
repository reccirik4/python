# -*- coding: utf-8 -*-
"""
DubSync Pro — SRT Parser + Diarizasyon Tanıma (srt_parser.py)

SRT, ASS ve VTT altyazı dosyalarını okur, zaman damgalarını ayrıştırır,
konuşmacı (speaker) etiketlerini otomatik algılar ve metin temizleme yapar.
"""

import re
import os
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

logger = logging.getLogger("DubSync.SrtParser")


# ============================================================
# Veri Yapıları
# ============================================================

@dataclass
class AltyaziSatiri:
    """Tek bir altyazı satırını temsil eder."""

    sira: int                           # Altyazı sıra numarası (1'den başlar)
    baslangic_ms: int                   # Başlangıç zamanı (milisaniye)
    bitis_ms: int                       # Bitiş zamanı (milisaniye)
    ham_metin: str                      # Orijinal metin ([SPEAKER_XX] dahil)
    temiz_metin: str                    # Temizlenmiş metin (seslendirme için)
    konusmaci_id: str = ""              # Otomatik algılanan konuşmacı kimliği
    konusmaci_isim: str = ""            # Kullanıcının atadığı isim
    sure_ms: int = 0                    # Süre (milisaniye, otomatik hesaplanır)

    def __post_init__(self):
        self.sure_ms = max(0, self.bitis_ms - self.baslangic_ms)

    @property
    def baslangic_str(self) -> str:
        """Başlangıç zamanını 'SS:DD:SS,mmm' formatında döndürür."""
        return ms_to_srt_zaman(self.baslangic_ms)

    @property
    def bitis_str(self) -> str:
        """Bitiş zamanını 'SS:DD:SS,mmm' formatında döndürür."""
        return ms_to_srt_zaman(self.bitis_ms)

    @property
    def sure_sn(self) -> float:
        """Süreyi saniye olarak döndürür."""
        return self.sure_ms / 1000.0


@dataclass
class AltyaziDosyasi:
    """Bir altyazı dosyasının tamamını temsil eder."""

    dosya_yolu: str                     # Kaynak dosya yolu
    format: str = "srt"                 # "srt", "ass", "vtt"
    satirlar: list = field(default_factory=list)  # AltyaziSatiri listesi
    konusmacilar: dict = field(default_factory=dict)  # {id: {"sayi": N, "isim": ""}}
    kodlama: str = "utf-8"              # Algılanan karakter kodlaması
    toplam_sure_ms: int = 0             # Toplam süre (son altyazının bitiş zamanı)

    @property
    def satir_sayisi(self) -> int:
        return len(self.satirlar)

    @property
    def konusmaci_sayisi(self) -> int:
        return len(self.konusmacilar)


# ============================================================
# Zaman Dönüşüm Fonksiyonları
# ============================================================

def srt_zaman_to_ms(zaman_str: str) -> int:
    """
    SRT zaman damgasını milisaniyeye çevirir.

    Args:
        zaman_str: "01:23:45,678" veya "01:23:45.678" formatında.

    Returns:
        Milisaniye cinsinden zaman.

    Örnek:
        >>> srt_zaman_to_ms("01:23:45,678")
        5025678
    """
    zaman_str = zaman_str.strip().replace(".", ",")
    eslesme = re.match(
        r"(\d{1,2}):(\d{2}):(\d{2}),(\d{1,3})", zaman_str
    )
    if not eslesme:
        logger.warning("Geçersiz zaman damgası: '%s'", zaman_str)
        return 0

    saat, dakika, saniye, ms = eslesme.groups()
    # Milisaniye 1-2 haneli olabilir, 3 haneye tamamla
    ms = ms.ljust(3, "0")

    return (
        int(saat) * 3600000
        + int(dakika) * 60000
        + int(saniye) * 1000
        + int(ms)
    )


def ms_to_srt_zaman(ms: int) -> str:
    """
    Milisaniyeyi SRT zaman damgasına çevirir.

    Args:
        ms: Milisaniye cinsinden zaman.

    Returns:
        "01:23:45,678" formatında zaman dizesi.

    Örnek:
        >>> ms_to_srt_zaman(5025678)
        '01:23:45,678'
    """
    if ms < 0:
        ms = 0
    saat = ms // 3600000
    ms %= 3600000
    dakika = ms // 60000
    ms %= 60000
    saniye = ms // 1000
    milisaniye = ms % 1000
    return f"{saat:02d}:{dakika:02d}:{saniye:02d},{milisaniye:03d}"


# ============================================================
# Kodlama Algılama
# ============================================================

def kodlama_algila(dosya_yolu: str) -> str:
    """
    Dosyanın karakter kodlamasını algılar.

    Args:
        dosya_yolu: Dosya yolu.

    Returns:
        Kodlama adı (örn: "utf-8", "windows-1254").
    """
    try:
        import chardet
    except ImportError:
        logger.warning("chardet yüklü değil, utf-8 varsayılıyor.")
        return "utf-8"

    with open(dosya_yolu, "rb") as f:
        ham_veri = f.read(min(os.path.getsize(dosya_yolu), 100000))

    sonuc = chardet.detect(ham_veri)
    kodlama = sonuc.get("encoding", "utf-8") or "utf-8"
    guven = sonuc.get("confidence", 0)

    logger.info(
        "Kodlama algılandı: %s (güven: %.1f%%)", kodlama, guven * 100
    )

    # ascii ve ISO-8859-1 Türkçe'de sorun çıkarır, windows-1254'e yönlendir
    if kodlama.lower() in ("ascii", "iso-8859-1") and guven < 0.9:
        kodlama = "utf-8"

    return kodlama


# ============================================================
# Konuşmacı Algılama
# ============================================================

# Varsayılan diarizasyon desenleri
VARSAYILAN_DESENLER: list[str] = [
    r"\[SPEAKER_(\d+)\]",           # [SPEAKER_00]
    r"\(SPEAKER_(\d+)\)",           # (SPEAKER_00)
    r"SPEAKER_(\d+):",              # SPEAKER_00:
    r"\[([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)\]",  # [İsim]
    r"\(([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)\)",  # (İsim)
]


def konusmaci_algila(
    metin: str, desenler: Optional[list[str]] = None
) -> tuple[str, str]:
    """
    Metin içindeki konuşmacı etiketini algılar ve temiz metni döndürür.

    Args:
        metin: Ham altyazı metni (örn: "[SPEAKER_01] Hello world").
        desenler: Regex desen listesi. None ise varsayılanlar kullanılır.

    Returns:
        (konusmaci_id, temiz_metin) çifti.
        Konuşmacı bulunamazsa ("", orijinal_metin) döner.

    Örnekler:
        >>> konusmaci_algila("[SPEAKER_01] Hello world")
        ('SPEAKER_01', 'Hello world')

        >>> konusmaci_algila("(SPEAKER_00) Merhaba")
        ('SPEAKER_00', 'Merhaba')

        >>> konusmaci_algila("[Vladimir] Nasılsın?")
        ('Vladimir', 'Nasılsın?')

        >>> konusmaci_algila("Normal metin")
        ('', 'Normal metin')
    """
    if desenler is None:
        desenler = VARSAYILAN_DESENLER

    for desen in desenler:
        eslesme = re.match(r"\s*" + desen + r"\s*(.*)", metin, re.DOTALL)
        if eslesme:
            gruplar = eslesme.groups()
            if len(gruplar) >= 2:
                konusmaci_ham = gruplar[0].strip()
                temiz = gruplar[1].strip()

                # SPEAKER_XX formatında ise kimliği standartlaştır
                if re.match(r"^\d+$", konusmaci_ham):
                    konusmaci_id = f"SPEAKER_{konusmaci_ham.zfill(2)}"
                else:
                    konusmaci_id = konusmaci_ham

                return konusmaci_id, temiz

    return "", metin.strip()


# ============================================================
# SRT Ayrıştırıcı
# ============================================================

def srt_oku(dosya_yolu: str, desenler: Optional[list[str]] = None) -> AltyaziDosyasi:
    """
    SRT dosyasını okur ve ayrıştırır.

    Args:
        dosya_yolu: SRT dosya yolu.
        desenler: Diarizasyon regex desenleri. None ise varsayılanlar.

    Returns:
        AltyaziDosyasi nesnesi.

    Raises:
        FileNotFoundError: Dosya bulunamadı.
        ValueError: Dosya ayrıştırılamadı.
    """
    if not os.path.isfile(dosya_yolu):
        raise FileNotFoundError(f"SRT dosyası bulunamadı: {dosya_yolu}")

    # Kodlama algıla
    kodlama = kodlama_algila(dosya_yolu)

    # Dosyayı oku
    try:
        with open(dosya_yolu, "r", encoding=kodlama, errors="replace") as f:
            icerik = f.read()
    except OSError as e:
        raise ValueError(f"Dosya okunamadı: {e}") from e

    # BOM kaldır
    if icerik.startswith("\ufeff"):
        icerik = icerik[1:]

    # Satır sonlarını normalize et (CRLF → LF)
    icerik = icerik.replace("\r\n", "\n").replace("\r", "\n")

    # Boş satırlarla blokları ayır
    bloklar = re.split(r"\n\n+", icerik.strip())

    satirlar: list[AltyaziSatiri] = []
    konusmacilar: dict[str, dict] = {}
    son_bitis_ms: int = 0

    for blok in bloklar:
        satirlari = blok.strip().split("\n")
        if len(satirlari) < 2:
            continue

        # Sıra numarasını bul
        sira_str = satirlari[0].strip()
        if not sira_str.isdigit():
            continue
        sira = int(sira_str)

        # Zaman damgasını bul
        zaman_satirlari = satirlari[1].strip()
        zaman_eslesme = re.match(
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})",
            zaman_satirlari,
        )
        if not zaman_eslesme:
            logger.warning("Sıra %d: Geçersiz zaman damgası: '%s'", sira, zaman_satirlari)
            continue

        baslangic_ms = srt_zaman_to_ms(zaman_eslesme.group(1))
        bitis_ms = srt_zaman_to_ms(zaman_eslesme.group(2))

        # Metin satırlarını birleştir (3. satırdan itibaren)
        metin_satirlari = satirlari[2:]
        ham_metin = " ".join(satir.strip() for satir in metin_satirlari if satir.strip())

        if not ham_metin:
            continue

        # Konuşmacı algıla ve metni temizle
        konusmaci_id, temiz_metin = konusmaci_algila(ham_metin, desenler)

        # HTML tag'lerini temizle (<i>, <b>, vb.)
        temiz_metin = re.sub(r"<[^>]+>", "", temiz_metin).strip()

        # Çoklu boşlukları teke indir
        temiz_metin = re.sub(r"\s+", " ", temiz_metin).strip()

        if not temiz_metin:
            continue

        # Konuşmacı istatistiğini güncelle
        if konusmaci_id:
            if konusmaci_id not in konusmacilar:
                konusmacilar[konusmaci_id] = {"sayi": 0, "isim": ""}
            konusmacilar[konusmaci_id]["sayi"] += 1

        # AltyaziSatiri oluştur
        satir = AltyaziSatiri(
            sira=sira,
            baslangic_ms=baslangic_ms,
            bitis_ms=bitis_ms,
            ham_metin=ham_metin,
            temiz_metin=temiz_metin,
            konusmaci_id=konusmaci_id,
        )
        satirlar.append(satir)
        son_bitis_ms = max(son_bitis_ms, bitis_ms)

    if not satirlar:
        raise ValueError(f"Dosyada geçerli altyazı satırı bulunamadı: {dosya_yolu}")

    # Konuşmacıları satır sayısına göre sırala
    konusmacilar = dict(
        sorted(konusmacilar.items(), key=lambda x: x[1]["sayi"], reverse=True)
    )

    sonuc = AltyaziDosyasi(
        dosya_yolu=dosya_yolu,
        format="srt",
        satirlar=satirlar,
        konusmacilar=konusmacilar,
        kodlama=kodlama,
        toplam_sure_ms=son_bitis_ms,
    )

    logger.info(
        "SRT yüklendi: %d satır, %d konuşmacı, süre: %s",
        sonuc.satir_sayisi,
        sonuc.konusmaci_sayisi,
        ms_to_srt_zaman(son_bitis_ms),
    )

    return sonuc


# ============================================================
# ASS/SSA Ayrıştırıcı
# ============================================================

def ass_oku(dosya_yolu: str, desenler: Optional[list[str]] = None) -> AltyaziDosyasi:
    """
    ASS/SSA altyazı dosyasını okur.

    ASS formatında karakter bilgisi Style ve Actor alanlarında bulunur.

    Args:
        dosya_yolu: ASS/SSA dosya yolu.
        desenler: Ek diarizasyon desenleri (metin içi etiketler için).

    Returns:
        AltyaziDosyasi nesnesi.
    """
    if not os.path.isfile(dosya_yolu):
        raise FileNotFoundError(f"ASS dosyası bulunamadı: {dosya_yolu}")

    kodlama = kodlama_algila(dosya_yolu)

    with open(dosya_yolu, "r", encoding=kodlama, errors="replace") as f:
        icerik = f.read()

    if icerik.startswith("\ufeff"):
        icerik = icerik[1:]

    satirlar: list[AltyaziSatiri] = []
    konusmacilar: dict[str, dict] = {}
    son_bitis_ms: int = 0
    sira: int = 0

    # [Events] bölümünü bul
    events_basla = False
    format_alanlari: list[str] = []

    for satir in icerik.split("\n"):
        satir = satir.strip()

        if satir.lower() == "[events]":
            events_basla = True
            continue

        if not events_basla:
            continue

        # Başka bölüm başladıysa dur
        if satir.startswith("[") and satir.endswith("]"):
            break

        # Format satırı
        if satir.lower().startswith("format:"):
            format_str = satir.split(":", 1)[1].strip()
            format_alanlari = [a.strip().lower() for a in format_str.split(",")]
            continue

        # Dialogue satırı
        if not satir.lower().startswith("dialogue:"):
            continue

        if not format_alanlari:
            logger.warning("ASS: Format satırı bulunamadı, varsayılan kullanılıyor.")
            format_alanlari = [
                "layer", "start", "end", "style", "name",
                "marginl", "marginr", "marginv", "effect", "text",
            ]

        deger_str = satir.split(":", 1)[1].strip()
        # Son alan (text) virgül içerebilir, bu yüzden split sınırla
        degerler = deger_str.split(",", len(format_alanlari) - 1)

        if len(degerler) < len(format_alanlari):
            continue

        alan_map = dict(zip(format_alanlari, degerler))

        # Zaman ayrıştır (ASS formatı: H:MM:SS.CC)
        baslangic_str = alan_map.get("start", "").strip()
        bitis_str = alan_map.get("end", "").strip()

        baslangic_ms = _ass_zaman_to_ms(baslangic_str)
        bitis_ms = _ass_zaman_to_ms(bitis_str)

        # Metin al ve ASS tag'lerini temizle
        ham_metin = alan_map.get("text", "").strip()
        temiz_metin = re.sub(r"\{[^}]*\}", "", ham_metin)  # {\pos(x,y)} gibi tag'ler
        temiz_metin = temiz_metin.replace("\\N", " ").replace("\\n", " ")
        temiz_metin = re.sub(r"<[^>]+>", "", temiz_metin)
        temiz_metin = re.sub(r"\s+", " ", temiz_metin).strip()

        if not temiz_metin:
            continue

        # Konuşmacı: önce Name (Actor) alanına bak
        konusmaci_id = alan_map.get("name", "").strip()
        if not konusmaci_id:
            # Name yoksa Style alanını kullan
            konusmaci_id = alan_map.get("style", "").strip()

        # Metin içinde de konuşmacı etiketi olabilir
        if not konusmaci_id:
            konusmaci_id, temiz_metin = konusmaci_algila(temiz_metin, desenler)

        sira += 1

        if konusmaci_id:
            if konusmaci_id not in konusmacilar:
                konusmacilar[konusmaci_id] = {"sayi": 0, "isim": ""}
            konusmacilar[konusmaci_id]["sayi"] += 1

        satir_obj = AltyaziSatiri(
            sira=sira,
            baslangic_ms=baslangic_ms,
            bitis_ms=bitis_ms,
            ham_metin=ham_metin,
            temiz_metin=temiz_metin,
            konusmaci_id=konusmaci_id,
        )
        satirlar.append(satir_obj)
        son_bitis_ms = max(son_bitis_ms, bitis_ms)

    if not satirlar:
        raise ValueError(f"ASS dosyasında diyalog bulunamadı: {dosya_yolu}")

    konusmacilar = dict(
        sorted(konusmacilar.items(), key=lambda x: x[1]["sayi"], reverse=True)
    )

    sonuc = AltyaziDosyasi(
        dosya_yolu=dosya_yolu,
        format="ass",
        satirlar=satirlar,
        konusmacilar=konusmacilar,
        kodlama=kodlama,
        toplam_sure_ms=son_bitis_ms,
    )

    logger.info(
        "ASS yüklendi: %d satır, %d konuşmacı, süre: %s",
        sonuc.satir_sayisi,
        sonuc.konusmaci_sayisi,
        ms_to_srt_zaman(son_bitis_ms),
    )

    return sonuc


def _ass_zaman_to_ms(zaman_str: str) -> int:
    """
    ASS zaman formatını milisaniyeye çevirir.

    ASS formatı: H:MM:SS.CC (centisaniye, 2 hane)

    Args:
        zaman_str: "1:23:45.67" formatında.

    Returns:
        Milisaniye.
    """
    eslesme = re.match(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", zaman_str.strip())
    if not eslesme:
        return 0

    saat, dakika, saniye, centisaniye = eslesme.groups()
    return (
        int(saat) * 3600000
        + int(dakika) * 60000
        + int(saniye) * 1000
        + int(centisaniye) * 10
    )


# ============================================================
# VTT Ayrıştırıcı
# ============================================================

def vtt_oku(dosya_yolu: str, desenler: Optional[list[str]] = None) -> AltyaziDosyasi:
    """
    WebVTT altyazı dosyasını okur.

    Args:
        dosya_yolu: VTT dosya yolu.
        desenler: Diarizasyon desenleri.

    Returns:
        AltyaziDosyasi nesnesi.
    """
    if not os.path.isfile(dosya_yolu):
        raise FileNotFoundError(f"VTT dosyası bulunamadı: {dosya_yolu}")

    kodlama = kodlama_algila(dosya_yolu)

    with open(dosya_yolu, "r", encoding=kodlama, errors="replace") as f:
        icerik = f.read()

    if icerik.startswith("\ufeff"):
        icerik = icerik[1:]

    icerik = icerik.replace("\r\n", "\n").replace("\r", "\n")

    satirlar: list[AltyaziSatiri] = []
    konusmacilar: dict[str, dict] = {}
    son_bitis_ms: int = 0
    sira: int = 0

    # WEBVTT başlığını atla
    bloklar = re.split(r"\n\n+", icerik.strip())
    for blok in bloklar:
        blok_satirlari = blok.strip().split("\n")

        # WEBVTT başlığını atla
        if blok_satirlari[0].strip().upper().startswith("WEBVTT"):
            continue

        # NOTE bloklarını atla
        if blok_satirlari[0].strip().upper().startswith("NOTE"):
            continue

        # STYLE bloklarını atla
        if blok_satirlari[0].strip().upper().startswith("STYLE"):
            continue

        # Zaman damgası satırını bul
        zaman_satir_idx = -1
        for i, satir in enumerate(blok_satirlari):
            if "-->" in satir:
                zaman_satir_idx = i
                break

        if zaman_satir_idx < 0:
            continue

        # Zaman ayrıştır (VTT: HH:MM:SS.mmm veya MM:SS.mmm)
        zaman_satirlari = blok_satirlari[zaman_satir_idx].strip()
        zaman_eslesme = re.match(
            r"([\d:\.]+)\s*-->\s*([\d:\.]+)",
            zaman_satirlari,
        )
        if not zaman_eslesme:
            continue

        baslangic_ms = _vtt_zaman_to_ms(zaman_eslesme.group(1))
        bitis_ms = _vtt_zaman_to_ms(zaman_eslesme.group(2))

        # Metin: zaman satırından sonraki tüm satırlar
        metin_satirlari = blok_satirlari[zaman_satir_idx + 1:]
        ham_metin = " ".join(s.strip() for s in metin_satirlari if s.strip())

        if not ham_metin:
            continue

        # VTT konuşmacı formatı: <v İsim>metin</v>
        konusmaci_id = ""
        temiz_metin = ham_metin

        v_eslesme = re.match(r"<v\s+([^>]+)>(.*?)(?:</v>)?$", ham_metin, re.DOTALL)
        if v_eslesme:
            konusmaci_id = v_eslesme.group(1).strip()
            temiz_metin = v_eslesme.group(2).strip()
        else:
            konusmaci_id, temiz_metin = konusmaci_algila(ham_metin, desenler)

        # HTML tag temizle
        temiz_metin = re.sub(r"<[^>]+>", "", temiz_metin)
        temiz_metin = re.sub(r"\s+", " ", temiz_metin).strip()

        if not temiz_metin:
            continue

        sira += 1

        if konusmaci_id:
            if konusmaci_id not in konusmacilar:
                konusmacilar[konusmaci_id] = {"sayi": 0, "isim": ""}
            konusmacilar[konusmaci_id]["sayi"] += 1

        satir_obj = AltyaziSatiri(
            sira=sira,
            baslangic_ms=baslangic_ms,
            bitis_ms=bitis_ms,
            ham_metin=ham_metin,
            temiz_metin=temiz_metin,
            konusmaci_id=konusmaci_id,
        )
        satirlar.append(satir_obj)
        son_bitis_ms = max(son_bitis_ms, bitis_ms)

    if not satirlar:
        raise ValueError(f"VTT dosyasında altyazı bulunamadı: {dosya_yolu}")

    konusmacilar = dict(
        sorted(konusmacilar.items(), key=lambda x: x[1]["sayi"], reverse=True)
    )

    sonuc = AltyaziDosyasi(
        dosya_yolu=dosya_yolu,
        format="vtt",
        satirlar=satirlar,
        konusmacilar=konusmacilar,
        kodlama=kodlama,
        toplam_sure_ms=son_bitis_ms,
    )

    logger.info(
        "VTT yüklendi: %d satır, %d konuşmacı, süre: %s",
        sonuc.satir_sayisi,
        sonuc.konusmaci_sayisi,
        ms_to_srt_zaman(son_bitis_ms),
    )

    return sonuc


def _vtt_zaman_to_ms(zaman_str: str) -> int:
    """
    VTT zaman formatını milisaniyeye çevirir.

    VTT formatı: HH:MM:SS.mmm veya MM:SS.mmm

    Args:
        zaman_str: "01:23:45.678" veya "23:45.678" formatında.

    Returns:
        Milisaniye.
    """
    zaman_str = zaman_str.strip()

    # HH:MM:SS.mmm
    eslesme = re.match(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})", zaman_str)
    if eslesme:
        saat, dakika, saniye, ms = eslesme.groups()
        ms = ms.ljust(3, "0")
        return (
            int(saat) * 3600000
            + int(dakika) * 60000
            + int(saniye) * 1000
            + int(ms)
        )

    # MM:SS.mmm
    eslesme = re.match(r"(\d{1,2}):(\d{2})\.(\d{1,3})", zaman_str)
    if eslesme:
        dakika, saniye, ms = eslesme.groups()
        ms = ms.ljust(3, "0")
        return int(dakika) * 60000 + int(saniye) * 1000 + int(ms)

    return 0


# ============================================================
# Otomatik Format Algılama + Ana Okuma Fonksiyonu
# ============================================================

def altyazi_oku(
    dosya_yolu: str, desenler: Optional[list[str]] = None
) -> AltyaziDosyasi:
    """
    Altyazı dosyasını otomatik format algılama ile okur.

    Desteklenen formatlar: SRT, ASS/SSA, VTT.

    Args:
        dosya_yolu: Altyazı dosya yolu.
        desenler: Diarizasyon regex desenleri.

    Returns:
        AltyaziDosyasi nesnesi.

    Raises:
        FileNotFoundError: Dosya bulunamadı.
        ValueError: Desteklenmeyen format veya ayrıştırma hatası.
    """
    uzanti = Path(dosya_yolu).suffix.lower()

    if uzanti in (".ass", ".ssa"):
        return ass_oku(dosya_yolu, desenler)
    elif uzanti == ".vtt":
        return vtt_oku(dosya_yolu, desenler)
    elif uzanti == ".srt":
        return srt_oku(dosya_yolu, desenler)
    else:
        # Uzantı tanınmıyorsa içeriğe bakarak tahmin et
        try:
            with open(dosya_yolu, "r", encoding="utf-8", errors="replace") as f:
                basi = f.read(500)
        except OSError:
            basi = ""

        if "[Script Info]" in basi or "[V4+ Styles]" in basi:
            return ass_oku(dosya_yolu, desenler)
        elif basi.strip().upper().startswith("WEBVTT"):
            return vtt_oku(dosya_yolu, desenler)
        else:
            # Varsayılan: SRT olarak dene
            logger.warning(
                "Uzantı tanınmıyor ('%s'), SRT olarak okunuyor.", uzanti
            )
            return srt_oku(dosya_yolu, desenler)


# ============================================================
# Konuşmacı İsim Atama Yardımcısı
# ============================================================

def konusmaci_isim_ata(
    dosya: AltyaziDosyasi, atamalar: dict[str, str]
) -> None:
    """
    Konuşmacılara isim atar ve altyazı satırlarını günceller.

    Args:
        dosya: AltyaziDosyasi nesnesi.
        atamalar: {"SPEAKER_00": "Pozzo", "SPEAKER_01": "Vladimir"} gibi.
    """
    # Konuşmacı sözlüğünü güncelle
    for kid, isim in atamalar.items():
        if kid in dosya.konusmacilar:
            dosya.konusmacilar[kid]["isim"] = isim

    # Altyazı satırlarını güncelle
    for satir in dosya.satirlar:
        if satir.konusmaci_id in atamalar:
            satir.konusmaci_isim = atamalar[satir.konusmaci_id]

    logger.info("Konuşmacı isimleri atandı: %s", atamalar)
