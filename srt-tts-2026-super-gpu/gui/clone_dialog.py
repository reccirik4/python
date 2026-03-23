# -*- coding: utf-8 -*-
"""
DubSync Pro — Filmden Ses Klonlama Dialogu (clone_dialog.py)

Bir karakterin SRT satırlarını listeler, kullanıcının seçtiği
satırları videodan keser, birleştirir ve referans WAV oluşturur.
XTTS-v2 klonlama için minimum 6 saniye gerektirir.
"""

import logging
import os
import subprocess
import tempfile
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
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QGroupBox,
    QWidget,
    QAbstractItemView,
)

from core.srt_parser import AltyaziDosyasi, AltyaziSatiri

logger = logging.getLogger("DubSync.CloneDialog")

MIN_SURE_MS = 6000  # XTTS-v2 minimum 6 saniye


class CloneDialog(QDialog):
    """
    Filmden ses klonlama dialogu.

    Akış:
    1. Karakter satırları checkbox listesiyle gösterilir
    2. Kullanıcı istediği satırları seçer
    3. Toplam süre gösterilir (min 6sn uyarısı)
    4. "Kes ve Birleştir" → FFmpeg ile videodan segmentleri keser
    5. Tek WAV dosyası oluşturulur → referans ses olarak döner

    Kullanım:
        dialog = CloneDialog(video_yolu, dosya, karakter_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            referans_yolu = dialog.referans_yolu
    """

    def __init__(
        self,
        video_yolu: str,
        dosya: AltyaziDosyasi,
        karakter_id: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._video_yolu = video_yolu
        self._dosya = dosya
        self._karakter_id = karakter_id
        self._referans_yolu: str = ""

        # Karakter satırlarını filtrele
        self._satirlar = [
            s for s in dosya.satirlar
            if s.konusmaci_id == karakter_id
        ]

        self._olustur()

    def _olustur(self):
        """Dialog arayüzünü oluşturur."""
        self.setWindowTitle(f"🎬 Filmden Ses Klonla — {self._karakter_id}")
        self.setMinimumSize(700, 500)
        self.resize(750, 550)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Bilgi
        isim = ""
        bilgi = self._dosya.konusmacilar.get(self._karakter_id, {})
        if isinstance(bilgi, dict):
            isim = bilgi.get("isim", "")
        gosterim = isim or self._karakter_id

        lbl_info = QLabel(
            f"<b>{gosterim}</b> için filmden ses segmentleri seçin. "
            f"<br>XTTS-v2 klonlama için <b>minimum 6 saniye</b> net konuşma gereklidir. "
            f"10-15 saniye ideal sonuç verir."
        )
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("font-size: 12px; color: #333; padding: 4px;")
        layout.addWidget(lbl_info)

        # Hızlı seçim butonları
        secim_layout = QHBoxLayout()
        btn_hepsi = QPushButton("Tümünü Seç")
        btn_hepsi.setStyleSheet("font-size: 11px;")
        btn_hepsi.clicked.connect(self._tumunu_sec)
        secim_layout.addWidget(btn_hepsi)

        btn_temizle = QPushButton("Seçimi Temizle")
        btn_temizle.setStyleSheet("font-size: 11px;")
        btn_temizle.clicked.connect(self._secimi_temizle)
        secim_layout.addWidget(btn_temizle)

        btn_otomatik = QPushButton("Otomatik Seç (≥6sn)")
        btn_otomatik.setStyleSheet("font-size: 11px; font-weight: bold;")
        btn_otomatik.setToolTip(
            "En uzun satırlardan başlayarak toplamda 6+ saniye olacak kadar otomatik seçer"
        )
        btn_otomatik.clicked.connect(self._otomatik_sec)
        secim_layout.addWidget(btn_otomatik)

        secim_layout.addStretch()
        layout.addLayout(secim_layout)

        # Tablo
        self._tablo = QTableWidget()
        self._tablo.setColumnCount(5)
        self._tablo.setHorizontalHeaderLabels([
            "✓", "#", "Başlangıç", "Süre", "Metin"
        ])
        self._tablo.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._tablo.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self._tablo.setColumnWidth(0, 30)
        self._tablo.setColumnWidth(1, 45)
        self._tablo.setColumnWidth(2, 100)
        self._tablo.setColumnWidth(3, 55)
        self._tablo.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tablo.setAlternatingRowColors(True)
        self._tablo.setStyleSheet(
            "QTableWidget { font-size: 11px; background-color: #fff; "
            "color: #222; alternate-background-color: #f5f5f5; }"
            "QHeaderView::section { font-size: 11px; font-weight: bold; "
            "background-color: #e8e8e8; color: #333; padding: 3px; }"
        )
        self._tablo.verticalHeader().setVisible(False)

        self._tabloyu_doldur()
        layout.addWidget(self._tablo, stretch=1)

        # Süre bilgisi
        self._lbl_sure = QLabel("Seçili: 0.0 saniye (minimum 6.0 saniye)")
        self._lbl_sure.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 4px; color: #F44336;"
        )
        layout.addWidget(self._lbl_sure)

        # İlerleme
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        # Butonlar
        btn_layout = QHBoxLayout()

        self._btn_dosyadan = QPushButton("📁 Dosyadan Seç")
        self._btn_dosyadan.setStyleSheet("font-size: 11px; padding: 6px 14px;")
        self._btn_dosyadan.setToolTip("Hazır bir WAV/MP3 referans ses dosyası seçin")
        self._btn_dosyadan.clicked.connect(self._dosyadan_sec)
        btn_layout.addWidget(self._btn_dosyadan)

        btn_layout.addStretch()

        self._btn_iptal = QPushButton("İptal")
        self._btn_iptal.setStyleSheet("font-size: 11px; padding: 6px 14px;")
        self._btn_iptal.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_iptal)

        self._btn_kes = QPushButton("✂️ Kes ve Birleştir")
        self._btn_kes.setStyleSheet(
            "font-size: 11px; font-weight: bold; padding: 6px 18px; "
            "background-color: #4CAF50; color: white; border-radius: 4px;"
        )
        self._btn_kes.setEnabled(False)
        self._btn_kes.clicked.connect(self._kes_ve_birlestir)
        btn_layout.addWidget(self._btn_kes)

        layout.addLayout(btn_layout)

    # --------------------------------------------------------
    # Tablo
    # --------------------------------------------------------

    def _tabloyu_doldur(self):
        """Karakter satırlarını tabloya yazar."""
        self._tablo.setRowCount(len(self._satirlar))

        for idx, satir in enumerate(self._satirlar):
            # Checkbox
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            chk.setCheckState(Qt.CheckState.Unchecked)
            self._tablo.setItem(idx, 0, chk)

            # Sıra
            item_sira = QTableWidgetItem(str(satir.sira))
            item_sira.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_sira.setFlags(item_sira.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tablo.setItem(idx, 1, item_sira)

            # Başlangıç
            baslangic = self._ms_to_str(satir.baslangic_ms)
            item_bas = QTableWidgetItem(baslangic)
            item_bas.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_bas.setFlags(item_bas.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tablo.setItem(idx, 2, item_bas)

            # Süre
            sure_sn = satir.sure_ms / 1000
            item_sure = QTableWidgetItem(f"{sure_sn:.1f}s")
            item_sure.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_sure.setFlags(item_sure.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tablo.setItem(idx, 3, item_sure)

            # Metin
            item_metin = QTableWidgetItem(satir.temiz_metin)
            item_metin.setFlags(item_metin.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tablo.setItem(idx, 4, item_metin)

        # Checkbox değişim sinyali
        self._tablo.itemChanged.connect(self._secim_degisti)

        # Satıra tıklayınca checkbox toggle
        self._tablo.cellClicked.connect(self._satir_tiklandi)

    # --------------------------------------------------------
    # Seçim Yönetimi
    # --------------------------------------------------------

    def _satir_tiklandi(self, satir: int, sutun: int):
        """Satıra tıklanınca checkbox'ı toggle eder."""
        if sutun == 0:
            return  # Checkbox sütununa doğrudan tıklandıysa zaten çalışıyor
        chk = self._tablo.item(satir, 0)
        if chk is None:
            return
        if chk.checkState() == Qt.CheckState.Checked:
            chk.setCheckState(Qt.CheckState.Unchecked)
        else:
            chk.setCheckState(Qt.CheckState.Checked)

    def _secili_satirlar(self) -> list[AltyaziSatiri]:
        """Checkbox'ı işaretli satırları döndürür."""
        secili = []
        for idx in range(self._tablo.rowCount()):
            chk = self._tablo.item(idx, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                secili.append(self._satirlar[idx])
        return secili

    def _secili_sure_ms(self) -> int:
        """Seçili satırların toplam süresini (ms) döndürür."""
        return sum(s.sure_ms for s in self._secili_satirlar())

    def _secim_degisti(self, item):
        """Checkbox değiştiğinde süre bilgisini günceller."""
        if item.column() != 0:
            return

        sure_ms = self._secili_sure_ms()
        sure_sn = sure_ms / 1000
        secili_sayi = len(self._secili_satirlar())

        if sure_ms >= MIN_SURE_MS:
            renk = "#4CAF50"  # Yeşil
            durum = "✅ Yeterli"
        elif sure_ms > 0:
            renk = "#FF9800"  # Turuncu
            durum = "⚠️ Yetersiz"
        else:
            renk = "#F44336"  # Kırmızı
            durum = "❌ Seçim yapın"

        self._lbl_sure.setText(
            f"{durum} — Seçili: {secili_sayi} satır, "
            f"{sure_sn:.1f} saniye (minimum 6.0 saniye)"
        )
        self._lbl_sure.setStyleSheet(
            f"font-size: 12px; font-weight: bold; padding: 4px; color: {renk};"
        )

        self._btn_kes.setEnabled(sure_ms >= MIN_SURE_MS)

    def _tumunu_sec(self):
        """Tüm satırları seçer."""
        self._tablo.blockSignals(True)
        for idx in range(self._tablo.rowCount()):
            self._tablo.item(idx, 0).setCheckState(Qt.CheckState.Checked)
        self._tablo.blockSignals(False)
        # Manuel güncelle
        self._secim_degisti(self._tablo.item(0, 0))

    def _secimi_temizle(self):
        """Tüm seçimleri kaldırır."""
        self._tablo.blockSignals(True)
        for idx in range(self._tablo.rowCount()):
            self._tablo.item(idx, 0).setCheckState(Qt.CheckState.Unchecked)
        self._tablo.blockSignals(False)
        self._secim_degisti(self._tablo.item(0, 0))

    def _otomatik_sec(self):
        """En uzun satırlardan başlayarak 6+ saniye olacak kadar seçer."""
        self._secimi_temizle()

        # Süreye göre sırala (en uzun önce)
        indexed = [(idx, self._satirlar[idx].sure_ms) for idx in range(len(self._satirlar))]
        indexed.sort(key=lambda x: x[1], reverse=True)

        toplam = 0
        secilecek = []
        for idx, sure in indexed:
            secilecek.append(idx)
            toplam += sure
            if toplam >= MIN_SURE_MS + 2000:  # 8sn hedefle (güvenlik payı)
                break

        self._tablo.blockSignals(True)
        for idx in secilecek:
            self._tablo.item(idx, 0).setCheckState(Qt.CheckState.Checked)
        self._tablo.blockSignals(False)
        self._secim_degisti(self._tablo.item(0, 0))

    # --------------------------------------------------------
    # Kes ve Birleştir
    # --------------------------------------------------------

    def _kes_ve_birlestir(self):
        """
        Seçili satırları videodan keser ve tek WAV olarak birleştirir.

        FFmpeg kullanır:
        1. Her segment için videodan ses çıkar
        2. Segmentleri birleştir
        3. 48kHz mono WAV olarak kaydet
        """
        secili = self._secili_satirlar()
        if not secili:
            return

        if not os.path.isfile(self._video_yolu):
            QMessageBox.warning(
                self, "Hata", "Video dosyası bulunamadı!"
            )
            return

        # FFmpeg kontrolü
        import shutil
        if not shutil.which("ffmpeg"):
            QMessageBox.warning(
                self, "Hata",
                "FFmpeg bulunamadı! Lütfen FFmpeg'i kurun ve PATH'e ekleyin."
            )
            return

        self._progress.setVisible(True)
        self._progress.setMaximum(len(secili) + 1)
        self._progress.setValue(0)
        self._btn_kes.setEnabled(False)
        self._btn_kes.setText("Kesiliyor...")

        try:
            gecici_dir = tempfile.mkdtemp(prefix="dubsync_clone_")
            segment_dosyalar = []

            for i, satir in enumerate(secili):
                self._progress.setValue(i)

                baslangic_sn = satir.baslangic_ms / 1000
                sure_sn = satir.sure_ms / 1000

                # Çok kısa segmentleri atla
                if sure_sn < 0.2:
                    continue

                seg_yol = os.path.join(gecici_dir, f"seg_{i:04d}.wav")

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{baslangic_sn:.3f}",
                    "-i", self._video_yolu,
                    "-t", f"{sure_sn:.3f}",
                    "-vn",                     # Video yok
                    "-ac", "1",                # Mono
                    "-ar", "48000",            # 48kHz
                    "-acodec", "pcm_s24le",    # 24-bit WAV
                    seg_yol,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt" else 0
                    ),
                )

                if os.path.isfile(seg_yol) and os.path.getsize(seg_yol) > 100:
                    segment_dosyalar.append(seg_yol)
                else:
                    logger.warning(
                        "Segment kesilemedi: satır %d (%s)",
                        satir.sira, result.stderr.decode()[-200:] if result.stderr else ""
                    )

            if not segment_dosyalar:
                QMessageBox.warning(self, "Hata", "Hiç segment kesilemedi!")
                return

            # Segmentleri birleştir
            self._progress.setValue(len(secili))

            # Çıkış dosyası
            cikis_dir = os.path.join(
                str(Path(self._video_yolu).parent), "dubsync_clones"
            )
            os.makedirs(cikis_dir, exist_ok=True)
            cikis_yolu = os.path.join(
                cikis_dir,
                f"{self._karakter_id}_referans.wav"
            )

            if len(segment_dosyalar) == 1:
                # Tek segment — kopyala
                import shutil as sh
                sh.copy2(segment_dosyalar[0], cikis_yolu)
            else:
                # Birden fazla — FFmpeg concat
                liste_dosya = os.path.join(gecici_dir, "concat.txt")
                with open(liste_dosya, "w", encoding="utf-8") as f:
                    for seg in segment_dosyalar:
                        # Windows yol ayracı düzeltme
                        safe_path = seg.replace("\\", "/")
                        f.write(f"file '{safe_path}'\n")

                cmd_concat = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", liste_dosya,
                    "-ac", "1",
                    "-ar", "48000",
                    "-acodec", "pcm_s24le",
                    cikis_yolu,
                ]

                subprocess.run(
                    cmd_concat,
                    capture_output=True,
                    timeout=60,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt" else 0
                    ),
                )

            self._progress.setValue(len(secili) + 1)

            # Temizle
            import shutil as sh
            sh.rmtree(gecici_dir, ignore_errors=True)

            if os.path.isfile(cikis_yolu) and os.path.getsize(cikis_yolu) > 1000:
                self._referans_yolu = cikis_yolu
                toplam_sn = self._secili_sure_ms() / 1000

                QMessageBox.information(
                    self, "Başarılı",
                    f"Referans ses oluşturuldu!\n\n"
                    f"Dosya: {os.path.basename(cikis_yolu)}\n"
                    f"Segmentler: {len(segment_dosyalar)}\n"
                    f"Toplam süre: {toplam_sn:.1f} saniye\n"
                    f"Konum: {cikis_yolu}"
                )
                self.accept()
            else:
                QMessageBox.warning(
                    self, "Hata",
                    "Birleştirme başarısız — çıkış dosyası oluşturulamadı."
                )

        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Hata", "FFmpeg zaman aşımı!")
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Beklenmeyen hata: {e}")
            logger.error("Klonlama kesim hatası: %s", e, exc_info=True)
        finally:
            self._btn_kes.setEnabled(True)
            self._btn_kes.setText("✂️ Kes ve Birleştir")
            self._progress.setVisible(False)

    # --------------------------------------------------------
    # Dosyadan Seç (alternatif)
    # --------------------------------------------------------

    def _dosyadan_sec(self):
        """Hazır bir WAV/MP3 referans ses dosyası seçer."""
        yol, _ = QFileDialog.getOpenFileName(
            self,
            "Referans Ses Dosyası Seç",
            "",
            "Ses Dosyaları (*.wav *.mp3 *.ogg *.flac);;Tüm Dosyalar (*)",
        )
        if yol and os.path.isfile(yol):
            self._referans_yolu = yol
            self.accept()

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @staticmethod
    def _ms_to_str(ms: int) -> str:
        """Milisaniyeyi HH:MM:SS.mmm formatına çevirir."""
        toplam_sn = ms / 1000
        saat = int(toplam_sn // 3600)
        dakika = int((toplam_sn % 3600) // 60)
        saniye = toplam_sn % 60
        return f"{saat:02d}:{dakika:02d}:{saniye:06.3f}"

    @property
    def referans_yolu(self) -> str:
        """Oluşturulan veya seçilen referans ses dosyasının yolu."""
        return self._referans_yolu
