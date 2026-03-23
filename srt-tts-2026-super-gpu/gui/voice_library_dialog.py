# -*- coding: utf-8 -*-
"""
DubSync Pro — Ses Kütüphanesi Dialogu (voice_library_dialog.py)

Klonlanmış ve kaydedilmiş sesleri yönetir.
dubsync_voices/ klasöründe WAV + voices.json saklar.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QWidget,
    QAbstractItemView,
    QGroupBox,
    QFormLayout,
)

logger = logging.getLogger("DubSync.VoiceLibrary")

# Ses kütüphanesi klasörü — main.py'nin bulunduğu dizinde
VOICES_KLASOR_ADI = "dubsync_voices"
VOICES_JSON_ADI = "voices.json"


# ============================================================
# Ses Kütüphanesi Yöneticisi (singleton benzeri yardımcı)
# ============================================================

class VoiceLibrary:
    """
    dubsync_voices/ klasörünü ve voices.json'ı yönetir.

    Kullanım:
        lib = VoiceLibrary(proje_dizin)
        lib.ses_kaydet("Pozzo", "/tmp/gecici.wav", "filmden")
        sesler = lib.sesleri_listele()
    """

    def __init__(self, proje_dizin: str):
        """
        Args:
            proje_dizin: main.py'nin bulunduğu dizin.
        """
        self._proje_dizin = proje_dizin
        self._voices_klasor = os.path.join(proje_dizin, VOICES_KLASOR_ADI)
        self._json_yolu = os.path.join(self._voices_klasor, VOICES_JSON_ADI)
        self._meta: dict = {}
        self._klasor_hazirla()
        self._meta_yukle()

    def _klasor_hazirla(self):
        """Klasörü oluşturur."""
        os.makedirs(self._voices_klasor, exist_ok=True)

    def _meta_yukle(self):
        """voices.json'ı yükler."""
        if os.path.isfile(self._json_yolu):
            try:
                with open(self._json_yolu, "r", encoding="utf-8") as f:
                    self._meta = json.load(f)
            except Exception as e:
                logger.warning("voices.json okunamadı: %s", e)
                self._meta = {}
        else:
            self._meta = {}

    def _meta_kaydet(self):
        """voices.json'ı kaydeder."""
        try:
            with open(self._json_yolu, "w", encoding="utf-8") as f:
                json.dump(self._meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("voices.json kaydedilemedi: %s", e)

    def ses_kaydet(
        self,
        isim: str,
        kaynak_wav: str,
        referans_kaynak: str = "",
    ) -> Optional[str]:
        """
        Sesi kütüphaneye kaydeder.

        Args:
            isim: Ses adı (örn: "Pozzo").
            kaynak_wav: Geçici WAV dosya yolu.
            referans_kaynak: "filmden", "dosyadan" vb.

        Returns:
            Kaydedilen dosya yolu veya None.
        """
        if not isim or not isim.strip():
            return None
        if not os.path.isfile(kaynak_wav):
            return None

        # Dosya adını güvenli yap
        guvenli_isim = "".join(
            c for c in isim.strip()
            if c.isalnum() or c in (" ", "_", "-", "ğüşıöçĞÜŞİÖÇ")
        ).strip()
        if not guvenli_isim:
            guvenli_isim = f"ses_{datetime.now().strftime('%H%M%S')}"

        hedef_dosya = os.path.join(self._voices_klasor, f"{guvenli_isim}.wav")

        # Aynı isimde varsa numaralandır
        if os.path.isfile(hedef_dosya) and hedef_dosya != kaynak_wav:
            sayac = 2
            while os.path.isfile(hedef_dosya):
                hedef_dosya = os.path.join(
                    self._voices_klasor, f"{guvenli_isim}_{sayac}.wav"
                )
                sayac += 1

        try:
            shutil.copy2(kaynak_wav, hedef_dosya)
        except Exception as e:
            logger.error("Ses kopyalanamadı: %s", e)
            return None

        # Meta güncelle
        boyut_kb = os.path.getsize(hedef_dosya) // 1024
        self._meta[guvenli_isim] = {
            "dosya": os.path.basename(hedef_dosya),
            "tam_yol": hedef_dosya,
            "olusturma_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "referans_kaynak": referans_kaynak,
            "boyut_kb": boyut_kb,
        }
        self._meta_kaydet()

        logger.info("Ses kütüphaneye kaydedildi: %s → %s", isim, hedef_dosya)
        return hedef_dosya

    def ses_sil(self, isim: str) -> bool:
        """
        Sesi kütüphaneden siler.

        Returns:
            True: başarılı.
        """
        if isim not in self._meta:
            return False

        dosya_yolu = self._meta[isim].get("tam_yol", "")
        if os.path.isfile(dosya_yolu):
            try:
                os.remove(dosya_yolu)
            except Exception as e:
                logger.warning("Ses dosyası silinemedi: %s", e)

        del self._meta[isim]
        self._meta_kaydet()
        logger.info("Ses kütüphaneden silindi: %s", isim)
        return True

    def sesleri_listele(self) -> list[dict]:
        """
        Kütüphanedeki tüm sesleri listeler.
        Dosyası olmayan girişleri temizler.

        Returns:
            [{"isim": ..., "dosya": ..., "tam_yol": ..., ...}, ...]
        """
        temizlenenler = []
        sonuc = []

        for isim, bilgi in self._meta.items():
            tam_yol = bilgi.get("tam_yol", "")
            if not os.path.isfile(tam_yol):
                temizlenenler.append(isim)
                continue
            sonuc.append({"isim": isim, **bilgi})

        # Dosyası silinmiş girişleri temizle
        for isim in temizlenenler:
            del self._meta[isim]
        if temizlenenler:
            self._meta_kaydet()

        return sonuc

    def isim_mevcut_mu(self, isim: str) -> bool:
        """İsim kütüphanede var mı?"""
        return isim.strip() in self._meta

    @property
    def voices_klasor(self) -> str:
        return self._voices_klasor

    @property
    def ses_sayisi(self) -> int:
        return len(self._meta)


# ============================================================
# Ses Kütüphanesi Dialogu
# ============================================================

class VoiceLibraryDialog(QDialog):
    """
    Ses kütüphanesi yönetim dialogu.

    Kayıtlı sesleri listeler, önizleme ve silme sağlar.
    Dışarıdan ses kaydetmek için ses_kaydet_ve_goster() kullanılır.

    Kullanım:
        dialog = VoiceLibraryDialog(library, parent=self)
        dialog.exec()
    """

    ses_secildi = pyqtSignal(str, str)  # (isim, tam_yol)

    def __init__(
        self,
        library: VoiceLibrary,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._library = library
        self._secili_yol: str = ""

        self.setWindowTitle("🎙 Ses Kütüphanesi")
        self.setMinimumSize(600, 400)
        self.resize(650, 450)

        self._olustur()
        self._tabloyu_doldur()

    def _olustur(self):
        """Dialog arayüzünü oluşturur."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Başlık
        lbl_info = QLabel(
            f"<b>Ses Kütüphanesi</b> — "
            f"<span style='color:#888;font-size:11px;'>"
            f"{self._library.voices_klasor}</span>"
        )
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        # Tablo
        self._tablo = QTableWidget()
        self._tablo.setColumnCount(4)
        self._tablo.setHorizontalHeaderLabels(["İsim", "Boyut", "Tarih", "Kaynak"])
        self._tablo.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._tablo.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._tablo.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._tablo.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Fixed
        )
        self._tablo.setColumnWidth(1, 80)
        self._tablo.setColumnWidth(2, 130)
        self._tablo.setColumnWidth(3, 90)
        self._tablo.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tablo.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tablo.setAlternatingRowColors(True)
        self._tablo.setStyleSheet(
            "QTableWidget { font-size: 11px; background-color: #fff; "
            "color: #222; alternate-background-color: #f5f5f5; }"
            "QHeaderView::section { font-size: 11px; font-weight: bold; "
            "background-color: #e8e8e8; color: #333; padding: 3px; }"
        )
        self._tablo.verticalHeader().setVisible(False)
        self._tablo.selectionModel().selectionChanged.connect(self._secim_degisti)
        layout.addWidget(self._tablo, stretch=1)

        # Butonlar
        btn_layout = QHBoxLayout()

        self._btn_dinle = QPushButton("▶ Dinle")
        self._btn_dinle.setEnabled(False)
        self._btn_dinle.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 6px 14px; "
            "background-color: #e3f2fd; border: 1px solid #90caf9; border-radius: 4px; }"
            "QPushButton:hover { background-color: #bbdefb; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_dinle.clicked.connect(self._dinle)
        btn_layout.addWidget(self._btn_dinle)

        self._btn_sec = QPushButton("✓ Bu Sesi Kullan")
        self._btn_sec.setEnabled(False)
        self._btn_sec.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 6px 14px; "
            "background-color: #e8f5e9; border: 1px solid #81c784; border-radius: 4px; }"
            "QPushButton:hover { background-color: #c8e6c9; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_sec.clicked.connect(self._ses_sec)
        btn_layout.addWidget(self._btn_sec)

        btn_layout.addStretch()

        self._btn_sil = QPushButton("🗑 Sil")
        self._btn_sil.setEnabled(False)
        self._btn_sil.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 6px 14px; "
            "background-color: #ffebee; border: 1px solid #ef9a9a; border-radius: 4px; }"
            "QPushButton:hover { background-color: #ffcdd2; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_sil.clicked.connect(self._sil)
        btn_layout.addWidget(self._btn_sil)

        self._btn_kapat = QPushButton("Kapat")
        self._btn_kapat.setStyleSheet("font-size: 11px; padding: 6px 14px;")
        self._btn_kapat.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_kapat)

        layout.addLayout(btn_layout)

        # Bilgi etiketi
        self._lbl_bilgi = QLabel("")
        self._lbl_bilgi.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self._lbl_bilgi)

    def _tabloyu_doldur(self):
        """Kütüphanedeki sesleri tabloya yazar."""
        sesler = self._library.sesleri_listele()
        self._tablo.setRowCount(len(sesler))

        for idx, bilgi in enumerate(sesler):
            # İsim
            item_isim = QTableWidgetItem(bilgi["isim"])
            item_isim.setData(Qt.ItemDataRole.UserRole, bilgi.get("tam_yol", ""))
            self._tablo.setItem(idx, 0, item_isim)

            # Boyut
            boyut = bilgi.get("boyut_kb", 0)
            item_boyut = QTableWidgetItem(f"{boyut} KB")
            item_boyut.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, 1, item_boyut)

            # Tarih
            tarih = bilgi.get("olusturma_tarihi", "")
            item_tarih = QTableWidgetItem(tarih)
            item_tarih.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, 2, item_tarih)

            # Kaynak
            kaynak = bilgi.get("referans_kaynak", "")
            item_kaynak = QTableWidgetItem(kaynak)
            item_kaynak.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, 3, item_kaynak)

        sayi = len(sesler)
        self._lbl_bilgi.setText(
            f"{sayi} ses kayıtlı  |  Klasör: {self._library.voices_klasor}"
        )

    def _secim_degisti(self):
        """Satır seçimi değişince butonları günceller."""
        secili = self._tablo.selectedItems()
        var = bool(secili)
        self._btn_dinle.setEnabled(var)
        self._btn_sec.setEnabled(var)
        self._btn_sil.setEnabled(var)

        if var:
            satir = self._tablo.currentRow()
            item = self._tablo.item(satir, 0)
            if item:
                self._secili_yol = item.data(Qt.ItemDataRole.UserRole) or ""

    def _dinle(self):
        """Seçili sesi oynatır."""
        if not self._secili_yol or not os.path.isfile(self._secili_yol):
            QMessageBox.warning(self, "Hata", "Ses dosyası bulunamadı!")
            return

        try:
            import subprocess, sys
            if sys.platform == "win32":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self._secili_yol]
            elif sys.platform == "darwin":
                cmd = ["afplay", self._secili_yol]
            else:
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self._secili_yol]

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Ses oynatılamadı: {e}")

    def _ses_sec(self):
        """Seçili sesi emit eder ve dialogu kapatır."""
        satir = self._tablo.currentRow()
        if satir < 0:
            return
        item = self._tablo.item(satir, 0)
        if not item:
            return
        isim = item.text()
        tam_yol = item.data(Qt.ItemDataRole.UserRole) or ""
        if tam_yol and os.path.isfile(tam_yol):
            self.ses_secildi.emit(isim, tam_yol)
            self.accept()

    def _sil(self):
        """Seçili sesi siler."""
        satir = self._tablo.currentRow()
        if satir < 0:
            return
        item = self._tablo.item(satir, 0)
        if not item:
            return
        isim = item.text()

        cevap = QMessageBox.question(
            self, "Sil",
            f"'{isim}' sesi kütüphaneden ve diskten silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            self._library.ses_sil(isim)
            self._tabloyu_doldur()
            self._secili_yol = ""
            self._btn_dinle.setEnabled(False)
            self._btn_sec.setEnabled(False)
            self._btn_sil.setEnabled(False)

    def yenile(self):
        """Tabloyu yeniden yükler."""
        self._tabloyu_doldur()


# ============================================================
# Ses Kaydetme Dialogu (klonlama sonrası)
# ============================================================

class SesCalistirVeKaydetDialog(QDialog):
    """
    Klonlama tamamlandığında açılan dialog.

    - Üretilen sesi dinle
    - Yeniden üret
    - İsim ver ve kaydet

    Kullanım:
        dialog = SesCalistirVeKaydetDialog(
            gecici_wav, library, motor, referans_yolu, dil, parent
        )
        if dialog.exec() == Accepted:
            kaydedilen_yol = dialog.kaydedilen_yol
            kaydedilen_isim = dialog.kaydedilen_isim
    """

    # Thread-safe sinyal: True=başarılı, False=hatalı
    _uretim_sonuc = pyqtSignal(bool)

    def __init__(
        self,
        gecici_wav: str,
        library: VoiceLibrary,
        motor,             # XTTSEngine veya herhangi BaseEngine
        referans_yolu: str,
        dil: str = "tr",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._gecici_wav = gecici_wav
        self._library = library
        self._motor = motor
        self._referans_yolu = referans_yolu
        self._dil = dil
        self._kaydedilen_yol: str = ""
        self._kaydedilen_isim: str = ""
        self._uretiliyor: bool = False

        self.setWindowTitle("🎙 Klonlanan Sesi Kaydet")
        self.setMinimumSize(480, 300)
        self.resize(500, 320)
        self._olustur()
        # Thread-safe sinyal bağlantısı
        self._uretim_sonuc.connect(self._uretim_sonuc_slot)

    def _olustur(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Durum
        self._lbl_durum = QLabel("✅ Klonlama tamamlandı. Sesi dinleyip kaydedebilirsiniz.")
        self._lbl_durum.setStyleSheet("font-size: 12px; color: #4CAF50; font-weight: bold;")
        self._lbl_durum.setWordWrap(True)
        layout.addWidget(self._lbl_durum)

        # Dinle / Yeniden Üret
        oynat_layout = QHBoxLayout()

        self._btn_dinle = QPushButton("▶ Dinle")
        self._btn_dinle.setMinimumHeight(32)
        self._btn_dinle.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; padding: 4px 16px; "
            "background-color: #e3f2fd; border: 1px solid #90caf9; border-radius: 4px; }"
            "QPushButton:hover { background-color: #bbdefb; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_dinle.clicked.connect(self._dinle)
        oynat_layout.addWidget(self._btn_dinle)

        self._btn_yeniden = QPushButton("🔄 Yeniden Üret")
        self._btn_yeniden.setMinimumHeight(32)
        self._btn_yeniden.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 4px 16px; "
            "background-color: #fff8e1; border: 1px solid #ffe082; border-radius: 4px; }"
            "QPushButton:hover { background-color: #ffecb3; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_yeniden.clicked.connect(self._yeniden_uret)
        oynat_layout.addWidget(self._btn_yeniden)

        oynat_layout.addStretch()
        layout.addLayout(oynat_layout)

        # İsim + Kaydet
        kaydet_grup = QGroupBox("Kütüphaneye Kaydet")
        kaydet_grup.setStyleSheet("QGroupBox { font-size: 11px; }")
        fl = QFormLayout(kaydet_grup)
        fl.setSpacing(6)

        self._txt_isim = QLineEdit()
        self._txt_isim.setPlaceholderText("Ses adı girin (örn: Vladimir, Pozzo)")
        self._txt_isim.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        fl.addRow("Ses adı:", self._txt_isim)

        self._lbl_uyari = QLabel("")
        self._lbl_uyari.setStyleSheet("font-size: 10px; color: #F44336;")
        fl.addRow(self._lbl_uyari)

        layout.addWidget(kaydet_grup)

        # Alt butonlar
        alt_layout = QHBoxLayout()
        alt_layout.addStretch()

        self._btn_iptal = QPushButton("İptal")
        self._btn_iptal.setStyleSheet("font-size: 11px; padding: 6px 14px;")
        self._btn_iptal.clicked.connect(self.reject)
        alt_layout.addWidget(self._btn_iptal)

        self._btn_kaydet = QPushButton("💾 Kaydet")
        self._btn_kaydet.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; padding: 6px 18px; "
            "background-color: #4CAF50; color: white; border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self._btn_kaydet.clicked.connect(self._kaydet)
        alt_layout.addWidget(self._btn_kaydet)

        layout.addLayout(alt_layout)

    def _dinle(self):
        """Geçici WAV'ı oynatır."""
        if not self._gecici_wav or not os.path.isfile(self._gecici_wav):
            QMessageBox.warning(self, "Hata", "Ses dosyası bulunamadı!")
            return
        try:
            import subprocess, sys
            if sys.platform == "win32":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self._gecici_wav]
            elif sys.platform == "darwin":
                cmd = ["afplay", self._gecici_wav]
            else:
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self._gecici_wav]

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Ses oynatılamadı: {e}")

    def _yeniden_uret(self):
        """Referans sesDen yeniden klonlar."""
        if not self._motor or not self._referans_yolu:
            return
        if not os.path.isfile(self._referans_yolu):
            QMessageBox.warning(self, "Hata", "Referans ses dosyası bulunamadı!")
            return

        self._butonlari_deaktif(True)
        self._lbl_durum.setText("⏳ Yeniden üretiliyor...")
        self._lbl_durum.setStyleSheet("font-size: 12px; color: #FF9800; font-weight: bold;")

        import threading
        threading.Thread(target=self._uretim_thread, daemon=True).start()

    def _uretim_thread(self):
        """Arka planda XTTS ile üretim yapar."""
        import asyncio
        import tempfile

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            test_cumlesi = self._test_cumlesi_sec(self._dil)

            gecici = os.path.join(
                tempfile.gettempdir(),
                f"dubsync_klon_{os.getpid()}_yeni.wav"
            )

            sonuc = loop.run_until_complete(
                self._motor.ses_uret(
                    metin=test_cumlesi,
                    ses_id=self._referans_yolu,
                    cikis_yolu=gecici,
                )
            )
            loop.close()

            if sonuc.basarili and os.path.isfile(gecici):
                self._gecici_wav = gecici
                # pyqtSignal ile ana thread'e ilet (thread-safe)
                self._uretim_sonuc.emit(True)
            else:
                self._uretim_sonuc.emit(False)
        except Exception as e:
            logger.error("Yeniden üretim hatası: %s", e)
            self._uretim_sonuc.emit(False)

    def _uretim_sonuc_slot(self, basarili: bool):
        """Ana thread'de çağrılır — pyqtSignal slot'u."""
        self._butonlari_deaktif(False)
        if basarili:
            self._lbl_durum.setText("✅ Yeniden üretildi. Dinleyip kaydedebilirsiniz.")
            self._lbl_durum.setStyleSheet("font-size: 12px; color: #4CAF50; font-weight: bold;")
        else:
            self._lbl_durum.setText("❌ Üretim başarısız. Tekrar deneyin.")
            self._lbl_durum.setStyleSheet("font-size: 12px; color: #F44336; font-weight: bold;")

    def _butonlari_deaktif(self, deaktif: bool):
        """Üretim sırasında butonları kilitler/açar."""
        self._btn_dinle.setEnabled(not deaktif)
        self._btn_yeniden.setEnabled(not deaktif)
        self._btn_kaydet.setEnabled(not deaktif)
        self._btn_iptal.setEnabled(not deaktif)

    def _kaydet(self):
        """Sesi kütüphaneye kaydeder."""
        isim = self._txt_isim.text().strip()
        if not isim:
            self._lbl_uyari.setText("Ses adı boş olamaz!")
            return

        if self._library.isim_mevcut_mu(isim):
            cevap = QMessageBox.question(
                self, "Üzerine Yaz",
                f"'{isim}' zaten mevcut. Üzerine yazılsın mı?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if cevap != QMessageBox.StandardButton.Yes:
                return

        kaydedilen = self._library.ses_kaydet(
            isim=isim,
            kaynak_wav=self._gecici_wav,
            referans_kaynak="klonlama",
        )

        if kaydedilen:
            self._kaydedilen_yol = kaydedilen
            self._kaydedilen_isim = isim
            self.accept()
        else:
            self._lbl_uyari.setText("Kaydetme başarısız!")

    @staticmethod
    def _test_cumlesi_sec(dil: str) -> str:
        """Dile göre test cümlesi seçer."""
        cumleler = {
            "tr": "Merhaba, bu bir ses klonlama testidir.",
            "en": "Hello, this is a voice cloning test.",
            "de": "Hallo, dies ist ein Sprachklon-Test.",
            "fr": "Bonjour, ceci est un test de clonage vocal.",
            "es": "Hola, esta es una prueba de clonación de voz.",
            "it": "Ciao, questo è un test di clonazione vocale.",
            "ru": "Привет, это тест клонирования голоса.",
            "ja": "こんにちは、これは音声クローンテストです。",
            "ko": "안녕하세요, 이것은 음성 복제 테스트입니다.",
            "zh-cn": "你好，这是一个语音克隆测试。",
        }
        return cumleler.get(dil, "Hello, this is a voice cloning test.")

    @property
    def kaydedilen_yol(self) -> str:
        return self._kaydedilen_yol

    @property
    def kaydedilen_isim(self) -> str:
        return self._kaydedilen_isim
