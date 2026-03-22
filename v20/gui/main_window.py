# -*- coding: utf-8 -*-
"""
DubSync Pro — Ana Pencere (main_window.py)

PyQt6 tabanlı tam ekran destekli, scrollable ana pencere.
Sol: Karakter paneli, Orta: Altyazı tablosu, Sağ: Ayarlar + Ducking.
Alt: İlerleme çubuğu, kontrol butonları, log alanı.
"""

import os
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QScrollArea,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QProgressBar,
    QTextEdit,
    QGroupBox,
    QMenuBar,
    QStatusBar,
    QMessageBox,
    QSizePolicy,
    QFrame,
    QApplication,
)

from core.config_manager import ConfigManager
from gui.character_panel import CharacterPanel
from gui.subtitle_table import SubtitleTable
from gui.settings_panel import SettingsPanel
from gui.ducking_panel import DuckingPanel
from gui.preview_player import PreviewPlayer

logger = logging.getLogger("DubSync.MainWindow")

VERSION = "1.0.0"


class MainWindow(QMainWindow):
    """
    DubSync Pro ana penceresi.

    Yapı:
    ┌─────────────────────────────────────────────────┐
    │  Menü Çubuğu                                     │
    ├─────────────────────────────────────────────────┤
    │  Dosya Seçiciler (SRT, Video)                    │
    ├──────────┬──────────────────────┬───────────────┤
    │ Karakter │   Altyazı Tablosu    │    Ayarlar    │
    │ Paneli   │   (Scrollable)       │    Paneli     │
    │          │                      │    Ducking    │
    ├──────────┴──────────────────────┴───────────────┤
    │  Kontrol: [Başlat] [Duraklat] [İptal]           │
    │  İlerleme Çubuğu: ████████░░░░░ %65             │
    │  Log Alanı                                       │
    └─────────────────────────────────────────────────┘
    """

    # ── Thread-safe sinyaller (arka plan → ana thread) ──
    _sinyal_log = pyqtSignal(str, str)           # (mesaj, seviye)
    _sinyal_ilerleme = pyqtSignal(float, str)    # (yuzde, mesaj)
    _sinyal_bitti = pyqtSignal(bool)             # (basarili)
    _sinyal_onizleme_log = pyqtSignal(str, str)  # önizleme thread'i için
    _sinyal_onizleme_oynat = pyqtSignal(str, str, str, int)  # (dosya, isim, metin, sure_ms)

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self._srt_yolu: str = ""
        self._video_yolu: str = ""
        self._altyazi_dosyasi = None  # AltyaziDosyasi nesnesi
        self._tts_manager = None      # TTSManager nesnesi (seslendirme sırasında)
        self._seslendirme_thread = None  # Arka plan thread'i

        self._pencere_ayarla()
        self._arayuz_olustur()
        self._menu_olustur()
        self._baglantilari_kur()
        self._stil_uygula()

        # Panellere config yükle
        self._ayarlar_panel.config_yukle(self._config)
        self._ducking_panel.config_yukle(self._config)

        # ── Sinyal-slot bağlantıları (thread → GUI) ──
        self._sinyal_log.connect(self._slot_log)
        self._sinyal_ilerleme.connect(self._slot_ilerleme)
        self._sinyal_bitti.connect(self._slot_bitti)
        self._sinyal_onizleme_log.connect(self._slot_log)
        self._sinyal_onizleme_oynat.connect(self._slot_onizleme_oynat)

        logger.info("Ana pencere oluşturuldu.")

    # --------------------------------------------------------
    # Thread-safe slotlar (ana thread'de çalışır)
    # --------------------------------------------------------

    def _slot_log(self, mesaj: str, seviye: str):
        """Sinyal ile gelen log mesajını GUI'de gösterir."""
        self.log(mesaj, seviye)

    def _slot_ilerleme(self, yuzde: float, mesaj: str):
        """Sinyal ile gelen ilerleme bilgisini GUI'de gösterir."""
        self._ilerleme_guncelle(yuzde, mesaj)

    def _slot_bitti(self, basarili: bool):
        """Pipeline bittiğinde butonları sıfırlar."""
        self._btn_baslat.setEnabled(True)
        self._btn_duraklat.setEnabled(False)
        self._btn_iptal.setEnabled(False)
        self._btn_duraklat.setText("⏸  Duraklat")
        if basarili:
            self._ilerleme_guncelle(100, "Tamamlandı!")
        else:
            self._ilerleme_guncelle(0, "Başarısız.")

    def _slot_onizleme_oynat(self, dosya: str, isim: str, metin: str, sure_ms: int):
        """Önizleme thread'inden gelen ses dosyasını oynatır."""
        self._onizleme_player.dosya_yukle(dosya, isim, metin, sure_ms)
        self._onizleme_player._oynat()

    # --------------------------------------------------------
    # Pencere Ayarları
    # --------------------------------------------------------

    def _pencere_ayarla(self):
        """Pencere başlığı, boyutu ve ikonunu ayarlar."""
        self.setWindowTitle(f"DubSync Pro v{VERSION} — Film Seslendirme Aracı")

        genislik = self._config.al("genel.pencere_genislik", 1400)
        yukseklik = self._config.al("genel.pencere_yukseklik", 900)
        self.resize(genislik, yukseklik)

        if self._config.al("genel.pencere_tam_ekran", False):
            self.showMaximized()

        # Minimum boyut
        self.setMinimumSize(900, 600)

    # --------------------------------------------------------
    # Arayüz Oluşturma
    # --------------------------------------------------------

    def _arayuz_olustur(self):
        """Tüm GUI bileşenlerini oluşturur ve yerleştirir."""

        # Ana scroll area (tüm pencere scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        # Ana konteyner widget
        ana_widget = QWidget()
        ana_layout = QVBoxLayout(ana_widget)
        ana_layout.setSpacing(8)
        ana_layout.setContentsMargins(10, 10, 10, 10)

        # --- 1. Dosya Seçiciler ---
        dosya_grubu = self._dosya_seciciler_olustur()
        ana_layout.addWidget(dosya_grubu)

        # --- 2. Ana İçerik (3 sütun: Karakter | Altyazı | Ayarlar) ---
        splitter = self._ana_icerik_olustur()
        ana_layout.addWidget(splitter, stretch=1)

        # --- 3. Kontrol Paneli ---
        kontrol_grubu = self._kontrol_paneli_olustur()
        ana_layout.addWidget(kontrol_grubu)

        # --- 4. İlerleme ---
        ilerleme_grubu = self._ilerleme_olustur()
        ana_layout.addWidget(ilerleme_grubu)

        # --- 5. Log Alanı ---
        log_grubu = self._log_alani_olustur()
        ana_layout.addWidget(log_grubu)

        scroll.setWidget(ana_widget)
        self.setCentralWidget(scroll)

        # Durum çubuğu
        self.statusBar().showMessage("Hazır. Bir SRT ve video dosyası seçin.")

    # --------------------------------------------------------
    # Dosya Seçiciler
    # --------------------------------------------------------

    def _dosya_seciciler_olustur(self) -> QGroupBox:
        """SRT ve Video dosya seçici alanını oluşturur."""
        grup = QGroupBox("Dosya Seçimi")
        layout = QGridLayout(grup)
        layout.setSpacing(6)

        # SRT satırı
        lbl_srt = QLabel("📋 SRT Dosyası:")
        lbl_srt.setFixedWidth(110)
        self._txt_srt = QLineEdit()
        self._txt_srt.setPlaceholderText("Altyazı dosyası seçin (.srt, .ass, .vtt)")
        self._txt_srt.setReadOnly(True)
        self._btn_srt = QPushButton("Aç")
        self._btn_srt.setFixedWidth(70)

        layout.addWidget(lbl_srt, 0, 0)
        layout.addWidget(self._txt_srt, 0, 1)
        layout.addWidget(self._btn_srt, 0, 2)

        # Video satırı
        lbl_video = QLabel("🎬 Video Dosyası:")
        lbl_video.setFixedWidth(110)
        self._txt_video = QLineEdit()
        self._txt_video.setPlaceholderText("Video dosyası seçin (.mp4, .mkv, .avi)")
        self._txt_video.setReadOnly(True)
        self._btn_video = QPushButton("Aç")
        self._btn_video.setFixedWidth(70)

        layout.addWidget(lbl_video, 1, 0)
        layout.addWidget(self._txt_video, 1, 1)
        layout.addWidget(self._btn_video, 1, 2)

        # Bilgi satırı
        self._lbl_dosya_bilgi = QLabel("")
        self._lbl_dosya_bilgi.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._lbl_dosya_bilgi, 2, 0, 1, 3)

        layout.setColumnStretch(1, 1)
        return grup

    # --------------------------------------------------------
    # Ana İçerik (3 Sütun)
    # --------------------------------------------------------

    def _ana_icerik_olustur(self) -> QSplitter:
        """Sol: Karakter, Orta: Altyazı tablosu, Sağ: Ayarlar."""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Sol — Karakter Paneli
        self._karakter_panel = CharacterPanel()
        splitter.addWidget(self._karakter_panel)

        # Orta — Altyazı Tablosu
        self._altyazi_tablosu = SubtitleTable()
        splitter.addWidget(self._altyazi_tablosu)

        # Sağ — Ayarlar + Ducking (dikey stack)
        sag_widget = QWidget()
        sag_layout = QVBoxLayout(sag_widget)
        sag_layout.setContentsMargins(0, 0, 0, 0)
        sag_layout.setSpacing(6)

        self._ayarlar_panel = SettingsPanel()
        self._ducking_panel = DuckingPanel()
        self._onizleme_player = PreviewPlayer()

        sag_layout.addWidget(self._ayarlar_panel, stretch=2)
        sag_layout.addWidget(self._ducking_panel, stretch=1)
        sag_layout.addWidget(self._onizleme_player, stretch=1)

        splitter.addWidget(sag_widget)

        # Splitter oranları (sol:orta:sağ = 1:3:1)
        splitter.setSizes([250, 700, 250])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        return splitter

    # --------------------------------------------------------
    # Kontrol Paneli
    # --------------------------------------------------------

    def _kontrol_paneli_olustur(self) -> QWidget:
        """Başlat, Duraklat, İptal butonları."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        self._btn_baslat = QPushButton("▶  Başlat")
        self._btn_baslat.setMinimumHeight(38)
        self._btn_baslat.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; font-size: 14px; border-radius: 6px; "
            "padding: 6px 20px; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:disabled { background-color: #888; }"
        )

        self._btn_duraklat = QPushButton("⏸  Duraklat")
        self._btn_duraklat.setMinimumHeight(38)
        self._btn_duraklat.setEnabled(False)
        self._btn_duraklat.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; "
            "font-weight: bold; font-size: 14px; border-radius: 6px; "
            "padding: 6px 20px; }"
            "QPushButton:hover { background-color: #e68a00; }"
            "QPushButton:disabled { background-color: #888; }"
        )

        self._btn_iptal = QPushButton("⏹  İptal")
        self._btn_iptal.setMinimumHeight(38)
        self._btn_iptal.setEnabled(False)
        self._btn_iptal.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "font-weight: bold; font-size: 14px; border-radius: 6px; "
            "padding: 6px 20px; }"
            "QPushButton:hover { background-color: #d32f2f; }"
            "QPushButton:disabled { background-color: #888; }"
        )

        layout.addStretch()
        layout.addWidget(self._btn_baslat)
        layout.addWidget(self._btn_duraklat)
        layout.addWidget(self._btn_iptal)
        layout.addStretch()

        return widget

    # --------------------------------------------------------
    # İlerleme
    # --------------------------------------------------------

    def _ilerleme_olustur(self) -> QWidget:
        """İlerleme çubuğu ve durum etiketi."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Üst satır: durum metni
        ust = QHBoxLayout()
        self._lbl_ilerleme_durum = QLabel("Bekleniyor...")
        self._lbl_ilerleme_durum.setStyleSheet("font-size: 12px; color: #666;")
        self._lbl_ilerleme_yuzde = QLabel("")
        self._lbl_ilerleme_yuzde.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #333;"
        )
        self._lbl_ilerleme_yuzde.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        ust.addWidget(self._lbl_ilerleme_durum, stretch=1)
        ust.addWidget(self._lbl_ilerleme_yuzde)
        layout.addLayout(ust)

        # İlerleme çubuğu
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setMinimumHeight(22)
        self._progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #ccc; border-radius: 4px; "
            "text-align: center; background-color: #f0f0f0; }"
            "QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }"
        )
        layout.addWidget(self._progress_bar)

        return widget

    # --------------------------------------------------------
    # Log Alanı
    # --------------------------------------------------------

    def _log_alani_olustur(self) -> QGroupBox:
        """Log mesajları alanı."""
        grup = QGroupBox("Log")
        layout = QVBoxLayout(grup)

        self._txt_log = QTextEdit()
        self._txt_log.setReadOnly(True)
        self._txt_log.setMaximumHeight(120)
        self._txt_log.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 11px; background-color: #1e1e1e; color: #d4d4d4; "
            "border: 1px solid #444; border-radius: 4px; }"
        )

        layout.addWidget(self._txt_log)
        return grup

    # --------------------------------------------------------
    # Menü Çubuğu
    # --------------------------------------------------------

    def _menu_olustur(self):
        """Menü çubuğunu oluşturur."""
        menubar = self.menuBar()

        # Dosya menüsü
        dosya_menu = menubar.addMenu("Dosya")

        act_srt_ac = QAction("SRT Aç...", self)
        act_srt_ac.setShortcut("Ctrl+O")
        act_srt_ac.triggered.connect(self._srt_dosya_sec)
        dosya_menu.addAction(act_srt_ac)

        act_video_ac = QAction("Video Aç...", self)
        act_video_ac.setShortcut("Ctrl+Shift+O")
        act_video_ac.triggered.connect(self._video_dosya_sec)
        dosya_menu.addAction(act_video_ac)

        dosya_menu.addSeparator()

        act_ayar_kaydet = QAction("Ayarları Kaydet", self)
        act_ayar_kaydet.setShortcut("Ctrl+S")
        act_ayar_kaydet.triggered.connect(self._ayarlari_kaydet)
        dosya_menu.addAction(act_ayar_kaydet)

        act_ayar_sifirla = QAction("Ayarları Sıfırla", self)
        act_ayar_sifirla.triggered.connect(self._ayarlari_sifirla)
        dosya_menu.addAction(act_ayar_sifirla)

        dosya_menu.addSeparator()

        act_cikis = QAction("Çıkış", self)
        act_cikis.setShortcut("Ctrl+Q")
        act_cikis.triggered.connect(self.close)
        dosya_menu.addAction(act_cikis)

        # Araçlar menüsü
        araclar_menu = menubar.addMenu("Araçlar")

        act_onizleme = QAction("Seçili Satırı Önizle", self)
        act_onizleme.setShortcut("F5")
        act_onizleme.triggered.connect(self._satir_onizle)
        araclar_menu.addAction(act_onizleme)

        act_analiz = QAction("Zamanlama Analizi", self)
        act_analiz.setShortcut("F6")
        araclar_menu.addAction(act_analiz)

        # Yardım menüsü
        yardim_menu = menubar.addMenu("Yardım")

        act_hakkinda = QAction("Hakkında", self)
        act_hakkinda.triggered.connect(self._hakkinda_goster)
        yardim_menu.addAction(act_hakkinda)

    # --------------------------------------------------------
    # Sinyal Bağlantıları
    # --------------------------------------------------------

    def _baglantilari_kur(self):
        """Buton sinyal-slot bağlantıları."""
        self._btn_srt.clicked.connect(self._srt_dosya_sec)
        self._btn_video.clicked.connect(self._video_dosya_sec)
        self._btn_baslat.clicked.connect(self._seslendirme_baslat)
        self._btn_duraklat.clicked.connect(self._seslendirme_duraklat)
        self._btn_iptal.clicked.connect(self._seslendirme_iptal)

        # Karakter paneli → Dinle butonu
        self._karakter_panel.onizleme_istendi.connect(self._karakter_onizle)

        # Karakter paneli → Filmden klonla
        self._karakter_panel.filmden_klonla_istendi.connect(self._filmden_klonla)

        # Altyazı tablosu → Çift tık önizleme
        self._altyazi_tablosu.satir_cift_tiklandi.connect(self._satir_onizle_sira)

        # Ayarlar paneli → Dil değişimi
        self._ayarlar_panel.dil_degisti.connect(self._dil_degisti)

        # Ayarlar paneli → Herhangi bir ayar değişimi
        self._ayarlar_panel.ayarlar_degisti.connect(self._ayarlar_degisti_handler)

    # --------------------------------------------------------
    # Dosya Seçme
    # --------------------------------------------------------

    def _srt_dosya_sec(self):
        """SRT dosya seçme dialogu."""
        son_klasor = self._config.al("genel.son_srt_klasoru", "")
        yol, _ = QFileDialog.getOpenFileName(
            self,
            "Altyazı Dosyası Seç",
            son_klasor,
            "Altyazı Dosyaları (*.srt *.ass *.ssa *.vtt);;Tüm Dosyalar (*)",
        )
        if yol:
            self._srt_yolu = yol
            self._txt_srt.setText(yol)
            self._config.ayarla("genel.son_srt_klasoru", str(Path(yol).parent))
            self._dosya_bilgi_guncelle()
            self.statusBar().showMessage(f"SRT: {os.path.basename(yol)}")

            # SRT parse et ve tabloya/panellere yükle
            self._srt_yukle_ve_goster(yol)

    def _video_dosya_sec(self):
        """Video dosya seçme dialogu."""
        son_klasor = self._config.al("genel.son_video_klasoru", "")
        yol, _ = QFileDialog.getOpenFileName(
            self,
            "Video Dosyası Seç",
            son_klasor,
            "Video Dosyaları (*.mp4 *.mkv *.avi *.mov *.webm);;Tüm Dosyalar (*)",
        )
        if yol:
            self._video_yolu = yol
            self._txt_video.setText(yol)
            self._config.ayarla("genel.son_video_klasoru", str(Path(yol).parent))
            self.log(f"Video yüklendi: {os.path.basename(yol)}")
            self._dosya_bilgi_guncelle()
            self.statusBar().showMessage(f"Video: {os.path.basename(yol)}")

    def _dosya_bilgi_guncelle(self):
        """Dosya bilgi etiketini günceller."""
        bilgiler = []
        if self._srt_yolu:
            bilgiler.append(f"SRT: {os.path.basename(self._srt_yolu)}")
        if self._video_yolu:
            bilgiler.append(f"Video: {os.path.basename(self._video_yolu)}")
        self._lbl_dosya_bilgi.setText("  |  ".join(bilgiler))

    def _srt_yukle_ve_goster(self, yol: str):
        """
        SRT dosyasını parse eder, tabloya ve karakter paneline yükler.

        Args:
            yol: SRT dosya yolu.
        """
        try:
            from core.srt_parser import altyazi_oku

            dosya = altyazi_oku(yol)
            self._altyazi_dosyasi = dosya

            # Tabloya yükle
            self._altyazi_tablosu.altyazi_yukle(dosya)

            # Karakter paneline konuşmacıları yükle (4 motor listesiyle)
            self._karakter_panel.konusmacilari_yukle(dosya.konusmacilar, self._config)

            # Karakterleri config'e kaydet (yeni karakterler varsayılan motorla oluşturulur)
            try:
                self._karakter_panel.config_e_kaydet(self._config)
                self._config.kaydet()
            except Exception:
                pass

            # Log
            konusmaci_str = ""
            if dosya.konusmaci_sayisi > 0:
                konusmaci_str = f", {dosya.konusmaci_sayisi} konuşmacı"
            self.log(
                f"SRT yüklendi: {os.path.basename(yol)} "
                f"({dosya.satir_sayisi} satır{konusmaci_str})",
                "success",
            )

        except Exception as e:
            self._altyazi_dosyasi = None
            self.log(f"SRT yükleme hatası: {e}", "error")
            logger.error("SRT yükleme hatası: %s", e, exc_info=True)

    # --------------------------------------------------------
    # Seslendirme Kontrolü
    # --------------------------------------------------------

    def _seslendirme_baslat(self):
        """Seslendirme işlemini başlatır — tam pipeline."""
        if not self._srt_yolu:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir SRT dosyası seçin.")
            return
        if not self._video_yolu:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir video dosyası seçin.")
            return
        if not self._altyazi_dosyasi:
            QMessageBox.warning(self, "Uyarı", "SRT dosyası yüklenemedi.")
            return

        # Zaten çalışıyorsa engelle
        if self._seslendirme_thread and self._seslendirme_thread.is_alive():
            self.log("Seslendirme zaten devam ediyor.", "warning")
            return

        self._btn_baslat.setEnabled(False)
        self._btn_duraklat.setEnabled(True)
        self._btn_iptal.setEnabled(True)

        self.log("Seslendirme başlatılıyor...")
        self._ilerleme_guncelle(0, "Hazırlanıyor...")

        # Karakter panelindeki güncel verileri config'e kaydet (klon_yolu dahil)
        # Bu ana thread'de çalışır — GUI erişimi güvenli
        try:
            self._karakter_panel.config_e_kaydet(self._config)
            self._config.kaydet()
        except Exception:
            pass

        # Arka plan thread'inde pipeline'ı çalıştır
        import threading
        self._seslendirme_thread = threading.Thread(
            target=self._seslendirme_pipeline, daemon=True
        )
        self._seslendirme_thread.start()

    def _seslendirme_duraklat(self):
        """Seslendirmeyi duraklatır/devam ettirir."""
        if self._tts_manager and self._tts_manager.ilerleme:
            if self._btn_duraklat.text().startswith("⏸"):
                self._tts_manager.duraksat()
                self._btn_duraklat.setText("▶  Devam")
                self.log("Duraklatıldı.")
            else:
                self._tts_manager.devam_et()
                self._btn_duraklat.setText("⏸  Duraklat")
                self.log("Devam ediliyor...")
        else:
            if self._btn_duraklat.text().startswith("⏸"):
                self._btn_duraklat.setText("▶  Devam")
                self.log("Duraklatıldı.")
            else:
                self._btn_duraklat.setText("⏸  Duraklat")
                self.log("Devam ediliyor...")

    def _seslendirme_iptal(self):
        """Seslendirmeyi iptal eder."""
        cevap = QMessageBox.question(
            self,
            "İptal",
            "Seslendirme iptal edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            if self._tts_manager:
                self._tts_manager.iptal_et()
            self.log("İptal isteği gönderildi...", "warning")

    # --------------------------------------------------------
    # Seslendirme Pipeline (arka plan thread'inde çalışır)
    # --------------------------------------------------------

    def _seslendirme_pipeline(self):
        """
        Tam seslendirme pipeline'ı (arka plan thread'inde çalışır).

        ÖNEMLİ: Bu metod GUI widget'larına DOĞRUDAN erişmez.
        Tüm GUI güncellemeleri sinyal emit ederek yapılır.

        Adımlar:
        1. TTSManager oluştur ve motorları başlat
        2. Toplu TTS üretimi (her satır için ses dosyası)
        3. Zamanlama analizi
        4. Ses birleştirme (segmentleri tek WAV'a)
        5. Audio ducking (orijinal ses + TTS miksleme)
        6. Video export (video + mikslenen ses)
        """
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        video_yolu = self._video_yolu
        dosya = self._altyazi_dosyasi
        config = self._config

        # Çıkış klasörü
        cikis_ana = os.path.join(
            str(Path(video_yolu).parent), "dubsync_output"
        )
        os.makedirs(cikis_ana, exist_ok=True)
        segment_klasoru = os.path.join(cikis_ana, "segments")
        os.makedirs(segment_klasoru, exist_ok=True)

        try:
            # ── ADIM 1: TTSManager oluştur ve motorları başlat ──
            self._sinyal_log.emit("Adım 1/6: Motorlar başlatılıyor...", "info")
            self._sinyal_ilerleme.emit(2, "Motorlar başlatılıyor...")

            from core.tts_manager import TTSManager
            self._tts_manager = TTSManager(config)

            # Motorları otomatik kaydet (sync) ve başlat (async)
            kaydedilenler = self._tts_manager.otomatik_motor_kaydet()
            if kaydedilenler:
                loop.run_until_complete(self._tts_manager.motorlari_baslat())

            if not kaydedilenler:
                self._sinyal_log.emit("Hiçbir TTS motoru başlatılamadı!", "error")
                self._sinyal_bitti.emit(False)
                return

            self._sinyal_log.emit(
                f"  Motorlar hazır: {', '.join(kaydedilenler)}", "success"
            )

            # ── ADIM 2: Toplu TTS üretimi ──
            self._sinyal_log.emit(
                f"Adım 2/6: {dosya.satir_sayisi} satır seslendiriliyor...", "info"
            )
            self._sinyal_ilerleme.emit(5, "Ses üretimi...")

            def ilerleme_callback(ilerleme):
                """Her satır sonrası GUI'yi sinyal ile güncelle."""
                yuzde = 5 + (ilerleme.yuzde * 0.50)  # %5-%55 arası
                satir = ilerleme.mevcut_satir
                metin_kisa = ""
                if satir and satir.temiz_metin:
                    metin_kisa = satir.temiz_metin[:40]
                self._sinyal_ilerleme.emit(
                    yuzde,
                    f"Satır {ilerleme.tamamlanan}/{ilerleme.toplam}: {metin_kisa}..."
                )

            sonuclar = loop.run_until_complete(
                self._tts_manager.toplu_uret(
                    dosya, segment_klasoru, ilerleme_callback
                )
            )

            basarili = sum(1 for _, s in sonuclar if s.basarili)
            hatali = sum(1 for _, s in sonuclar if not s.basarili)
            self._sinyal_log.emit(
                f"  Ses üretimi tamamlandı: {basarili} başarılı, {hatali} hatalı",
                "success" if hatali == 0 else "warning",
            )

            if basarili == 0:
                self._sinyal_log.emit(
                    "Hiçbir ses üretilemedi! İşlem durduruluyor.", "error"
                )
                self._sinyal_bitti.emit(False)
                return

            # İptal kontrolü
            if self._tts_manager.ilerleme and self._tts_manager.ilerleme.iptal:
                self._sinyal_log.emit("Seslendirme iptal edildi.", "warning")
                self._sinyal_bitti.emit(False)
                return

            # ── ADIM 3: Zamanlama analizi ──
            self._sinyal_log.emit("Adım 3/6: Zamanlama analizi...", "info")
            self._sinyal_ilerleme.emit(58, "Zamanlama analizi...")

            from core.timing_analyzer import TimingAnalyzer
            analizor = TimingAnalyzer.ayarlardan_olustur(config)

            segmentler = {}
            zamanlama_sonuclari = {}
            for satir, sonuc in sonuclar:
                if sonuc.basarili and sonuc.dosya_yolu:
                    segmentler[satir.sira] = sonuc.dosya_yolu
                    zs = analizor.satir_analiz(satir, sonuc.sure_ms)
                    zamanlama_sonuclari[satir.sira] = zs

            # Rapor oluştur (AnalizRaporu doğrudan)
            from core.timing_analyzer import AnalizRaporu, ZamanlamaDurum
            rapor = AnalizRaporu()
            rapor.toplam_satir = len(zamanlama_sonuclari)
            for zs in zamanlama_sonuclari.values():
                rapor.sonuclar.append(zs)
                if zs.durum == ZamanlamaDurum.SIGIYOR:
                    rapor.sigiyor += 1
                elif zs.durum == ZamanlamaDurum.HAFIF_HIZLANDIR:
                    rapor.hafif_hizlandir += 1
                elif zs.durum == ZamanlamaDurum.ORTA_HIZLANDIR:
                    rapor.orta_hizlandir += 1
                elif zs.durum == ZamanlamaDurum.TASMA:
                    rapor.tasma += 1
                elif zs.durum == ZamanlamaDurum.BOS:
                    rapor.bos += 1
            self._sinyal_log.emit(
                f"  Zamanlama: {rapor.sigiyor} sığıyor, "
                f"{rapor.hafif_hizlandir + rapor.orta_hizlandir} hızlandırılacak, "
                f"{rapor.tasma} taşma",
                "info",
            )

            # ── ADIM 4: Ses birleştirme ──
            self._sinyal_log.emit(
                "Adım 4/6: Ses segmentleri birleştiriliyor...", "info"
            )
            self._sinyal_ilerleme.emit(65, "Ses birleştirme...")

            from core.audio_assembler import AudioAssembler
            birlesik_ses_yolu = os.path.join(cikis_ana, "tts_combined.wav")

            birlestirir = AudioAssembler.ayarlardan_olustur(config)

            from core.video_exporter import VideoExporter
            video_suresi_ms = VideoExporter.video_suresi_al(video_yolu)

            birlesim_sonuc = birlestirir.birlesir(
                dosya=dosya,
                segmentler=segmentler,
                zamanlama_sonuclari=zamanlama_sonuclari,
                cikis_yolu=birlesik_ses_yolu,
                video_sure_ms=video_suresi_ms,
            )

            if not os.path.isfile(birlesik_ses_yolu):
                self._sinyal_log.emit(
                    "Birleşik ses dosyası oluşturulamadı!", "error"
                )
                self._sinyal_bitti.emit(False)
                return

            self._sinyal_log.emit("  Birleşik ses hazır.", "success")

            # ── ADIM 5: Audio ducking ──
            self._sinyal_log.emit("Adım 5/6: Audio ducking...", "info")
            self._sinyal_ilerleme.emit(78, "Audio ducking...")

            from core.audio_ducker import AudioDucker
            ducker = AudioDucker.ayarlardan_olustur(config)
            mikslenmis_ses_yolu = os.path.join(cikis_ana, "final_mixed.wav")

            # Önce videodan orijinal sesi WAV'a çıkar
            orijinal_ses_yolu = os.path.join(cikis_ana, "orijinal_ses.wav")
            ses_cikarildi = AudioDucker.videodan_ses_cikar(
                video_yolu, orijinal_ses_yolu, sr=config.al("ses.ornekleme_hizi", 48000)
            )
            if not ses_cikarildi:
                self._sinyal_log.emit(
                    "Videodan ses çıkarılamadı! FFmpeg kontrol edin.", "error"
                )
                self._sinyal_bitti.emit(False)
                return

            ducking_modu = config.al("ducking.yontem", "basit")
            if ducking_modu == "sidechain":
                ducker.sidechain_duck(
                    orijinal_ses=orijinal_ses_yolu,
                    tts_ses=birlesik_ses_yolu,
                    cikis_yolu=mikslenmis_ses_yolu,
                )
            else:
                ducker.basit_duck(
                    orijinal_ses=orijinal_ses_yolu,
                    tts_ses=birlesik_ses_yolu,
                    dosya=dosya,
                    cikis_yolu=mikslenmis_ses_yolu,
                )

            if not os.path.isfile(mikslenmis_ses_yolu):
                self._sinyal_log.emit(
                    "Miksleme başarısız!", "error"
                )
                self._sinyal_bitti.emit(False)
                return

            self._sinyal_log.emit("  Miksleme tamamlandı.", "success")

            # ── ADIM 6: Video export ──
            self._sinyal_log.emit("Adım 6/6: Video oluşturuluyor...", "info")
            self._sinyal_ilerleme.emit(90, "Video export...")

            exporter = VideoExporter.ayarlardan_olustur(config)

            export_sonuc = exporter.export(
                video_yolu=video_yolu,
                ses_yolu=mikslenmis_ses_yolu,
            )

            if export_sonuc.basarili and os.path.isfile(export_sonuc.dosya_yolu):
                self._sinyal_log.emit(
                    f"Video hazır: {os.path.basename(export_sonuc.dosya_yolu)} "
                    f"({export_sonuc.dosya_boyutu_mb:.1f} MB)",
                    "success",
                )
                self._sinyal_bitti.emit(True)
            else:
                hata = export_sonuc.hata_mesaji or "Bilinmeyen hata"
                self._sinyal_log.emit(f"Video export başarısız: {hata}", "error")
                self._sinyal_bitti.emit(False)

        except Exception as e:
            logger.error("Seslendirme pipeline hatası: %s", e, exc_info=True)
            self._sinyal_log.emit(
                f"Seslendirme pipeline hatası: {e}", "error"
            )
            self._sinyal_bitti.emit(False)

        finally:
            try:
                if self._tts_manager and not loop.is_closed():
                    loop.run_until_complete(self._tts_manager.motorlari_kapat())
            except Exception:
                pass
            if not loop.is_closed():
                loop.close()

    # --------------------------------------------------------
    # Ses Önizleme
    # --------------------------------------------------------

    def _karakter_onizle(self, karakter_id: str):
        """
        Karakter panelindeki 'Dinle' butonuna basıldığında çağrılır.
        Kısa bir test metniyle TTS üretip PreviewPlayer'da oynatır.
        """
        import asyncio
        import tempfile

        # Karakter bilgisini al
        kart = self._karakter_panel._kartlar.get(karakter_id)
        if kart is None:
            self.log(f"Karakter bulunamadı: {karakter_id}", "error")
            return

        veri = kart.veri_al()
        isim = veri.get("isim", karakter_id)
        motor_adi = veri.get("motor", "")
        ses_id = veri.get("ses", "")

        if not motor_adi:
            self.log("Motor seçilmemiş.", "warning")
            return

        test_metin = f"Merhaba, ben {isim}. Bu bir ses önizlemesidir."
        self.log(f"Önizleme: {isim} ({motor_adi})...")

        # Async TTS üretimini çalıştır
        self._onizleme_uret(test_metin, motor_adi, ses_id, isim, veri)

    def _satir_onizle(self):
        """F5 veya menüden 'Seçili Satırı Önizle' — tablodaki seçili satırı seslendirir."""
        secili = self._altyazi_tablosu._secili_sira_numaralari()
        if not secili:
            self.log("Önizlemek için bir satır seçin.", "warning")
            return
        self._satir_onizle_sira(secili[0])

    def _satir_onizle_sira(self, sira: int):
        """Belirtilen sıra numaralı satırı seslendirir ve önizler."""
        if not self._altyazi_dosyasi:
            self.log("Önce bir SRT dosyası yükleyin.", "warning")
            return

        satir = self._altyazi_tablosu._satir_bul(sira)
        if satir is None:
            self.log(f"Satır bulunamadı: #{sira}", "error")
            return

        # Karakter bilgisini al
        karakter_id = satir.konusmaci_id
        kart = self._karakter_panel._kartlar.get(karakter_id)
        if kart:
            veri = kart.veri_al()
            motor_adi = veri.get("motor", "")
            ses_id = veri.get("ses", "")
        else:
            motor_adi = self._config.varsayilan_motor()
            ses_id = ""
            veri = {}

        if not motor_adi:
            motor_adi = self._config.varsayilan_motor()

        isim = satir.konusmaci_isim or karakter_id
        self.log(f"Satır #{sira} önizleme: \"{satir.temiz_metin[:50]}...\" ({isim})")

        self._onizleme_uret(satir.temiz_metin, motor_adi, ses_id, isim, veri)

    def _onizleme_uret(self, metin: str, motor_adi: str, ses_id: str, isim: str, veri: dict):
        """
        Async TTS üretimi başlatır ve sonucu PreviewPlayer'da oynatır.

        Sinyaller kullanarak thread-safe GUI güncellemesi yapar.
        """
        import asyncio
        import tempfile
        import threading

        gecici_dir = os.path.join(
            tempfile.gettempdir(), "dubsync_preview"
        )
        os.makedirs(gecici_dir, exist_ok=True)

        # Hız/perde
        hiz = veri.get("hiz", "+0%")
        perde = veri.get("perde", "+0Hz")

        def _uret_thread():
            """Arka planda TTS üretimi yapar — GUI'ye sinyal ile erişir."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Motoru bul veya oluştur
                from core.tts_manager import TTSManager
                from engines.base_engine import BaseEngine

                motor = None

                # Önce kayıtlı motorlardan bak
                if hasattr(self, '_tts_manager') and self._tts_manager:
                    motor = self._tts_manager._motorlar.get(motor_adi)

                # Motor yoksa hızlı oluştur
                if motor is None:
                    motor = self._hizli_motor_olustur(motor_adi)

                if motor is None:
                    self._sinyal_onizleme_log.emit(
                        f"Motor bulunamadı: {motor_adi}", "error"
                    )
                    if motor_adi == "xtts_v2":
                        self._sinyal_onizleme_log.emit(
                            "XTTS kurulumu:\n"
                            "  pip install coqui-tts>=0.27.0\n"
                            "  pip install transformers>=4.46.0,<4.57.0\n"
                            "  pip install torch torchaudio --index-url "
                            "https://download.pytorch.org/whl/cu126",
                            "warning",
                        )
                    return

                # Motor hazır değilse başlat
                if not motor.hazir:
                    try:
                        loop.run_until_complete(motor.baslat())
                    except Exception as baslat_hata:
                        hata_str = str(baslat_hata)
                        self._sinyal_onizleme_log.emit(
                            f"Motor başlatma hatası ({motor_adi}): {hata_str}",
                            "error",
                        )
                        if "coqui" in hata_str.lower() or "TTS" in hata_str:
                            self._sinyal_onizleme_log.emit(
                                "coqui-tts/transformers uyumsuzluğu olabilir.\n"
                                "Çözüm: pip install coqui-tts>=0.27.0 "
                                "transformers>=4.46.0,<4.57.0",
                                "warning",
                            )
                        elif "api_key" in hata_str.lower() or "401" in hata_str:
                            self._sinyal_onizleme_log.emit(
                                "API anahtarını kontrol edin.", "warning"
                            )
                        loop.close()
                        return

                if not motor.hazir:
                    self._sinyal_onizleme_log.emit(
                        f"Motor başlatılamadı: {motor_adi}", "error"
                    )
                    loop.close()
                    return

                # Dosya yolu
                import hashlib
                dosya_hash = hashlib.md5(
                    f"{metin}{motor_adi}{ses_id}".encode()
                ).hexdigest()[:8]
                cikis = os.path.join(gecici_dir, f"preview_{dosya_hash}.wav")

                # Üret — XTTS klonlama desteği
                klon_yolu = veri.get("klon_yolu", "")
                gercek_ses_id = ses_id

                if motor_adi == "xtts_v2" and klon_yolu and os.path.isfile(klon_yolu):
                    # XTTS'te ses_id = referans dosya yolu
                    gercek_ses_id = klon_yolu
                elif motor_adi == "xtts_v2" and (not klon_yolu or not os.path.isfile(klon_yolu or "")):
                    self._sinyal_onizleme_log.emit(
                        "XTTS önizleme için referans ses gerekli (🎤 Klonla veya 🎬 Filmden).",
                        "warning",
                    )
                    loop.close()
                    return

                sonuc = loop.run_until_complete(
                    motor.ses_uret(metin, gercek_ses_id, cikis, hiz=hiz, perde=perde)
                )
                loop.close()

                if sonuc.basarili and os.path.isfile(cikis):
                    # PreviewPlayer'a sinyal ile yükle (ana thread'de)
                    self._sinyal_onizleme_oynat.emit(
                        cikis, isim, metin[:60], sonuc.sure_ms
                    )
                    self._sinyal_onizleme_log.emit(
                        f"Önizleme hazır: {isim} ({sonuc.sure_ms}ms)",
                        "success",
                    )
                else:
                    hata = sonuc.hata_mesaji if sonuc else "Bilinmeyen hata"
                    self._sinyal_onizleme_log.emit(
                        f"Önizleme hatası: {hata}", "error"
                    )

            except Exception as e:
                self._sinyal_onizleme_log.emit(
                    f"Önizleme hatası: {e}", "error"
                )
                logger.error("Önizleme hatası: %s", e, exc_info=True)

        # Arka plan thread'inde çalıştır
        thread = threading.Thread(target=_uret_thread, daemon=True)
        thread.start()

    def _hizli_motor_olustur(self, motor_adi: str):
        """Önizleme için hızlıca motor oluşturur."""
        try:
            if motor_adi == "edge_tts":
                from engines.edge_engine import EdgeEngine
                ayarlar = {
                    "erkek_ses": self._config.al(
                        "tts_motorlari.edge_tts.erkek_ses", "tr-TR-AhmetNeural"
                    ),
                    "kadin_ses": self._config.al(
                        "tts_motorlari.edge_tts.kadin_ses", "tr-TR-EmelNeural"
                    ),
                }
                return EdgeEngine(ayarlar)

            elif motor_adi == "openai":
                from engines.openai_engine import OpenAIEngine
                return OpenAIEngine({
                    "api_key": self._config.al("tts_motorlari.openai.api_key", ""),
                    "model": self._config.al("tts_motorlari.openai.model", "tts-1-hd"),
                })

            elif motor_adi == "elevenlabs":
                from engines.elevenlabs_engine import ElevenLabsEngine
                return ElevenLabsEngine({
                    "api_key": self._config.al("tts_motorlari.elevenlabs.api_key", ""),
                    "model": self._config.al("tts_motorlari.elevenlabs.model", "eleven_multilingual_v2"),
                })

            elif motor_adi == "xtts_v2":
                from engines.xtts_engine import XTTSEngine
                return XTTSEngine({
                    "gpu_kullan": self._config.al("tts_motorlari.xtts_v2.gpu_kullan", True),
                    "dil": self._config.al("tts_motorlari.xtts_v2.dil", "tr"),
                })

        except Exception as e:
            logger.error("Motor oluşturma hatası (%s): %s", motor_adi, e)
        return None

    # --------------------------------------------------------
    # Filmden Ses Klonlama
    # --------------------------------------------------------

    def _filmden_klonla(self, karakter_id: str):
        """
        Karakter panelindeki '🎬 Filmden' butonuna basıldığında çağrılır.
        CloneDialog açar, sonucu karakter kartına referans ses olarak atar.
        """
        if not self._video_yolu:
            self.log("Filmden klonlama için önce video dosyası seçin.", "warning")
            QMessageBox.warning(
                self, "Video Gerekli",
                "Filmden ses klonlama için önce bir video dosyası seçmelisiniz."
            )
            return

        if not self._altyazi_dosyasi:
            self.log("Filmden klonlama için önce SRT dosyası yükleyin.", "warning")
            return

        from gui.clone_dialog import CloneDialog

        dialog = CloneDialog(
            video_yolu=self._video_yolu,
            dosya=self._altyazi_dosyasi,
            karakter_id=karakter_id,
            parent=self,
        )

        if dialog.exec() == CloneDialog.DialogCode.Accepted:
            referans = dialog.referans_yolu
            if referans and os.path.isfile(referans):
                # Karakter kartına referans ses ata
                kart = self._karakter_panel._kartlar.get(karakter_id)
                if kart:
                    kart.referans_ses_ayarla(referans)
                self.log(
                    f"Klonlama referansı atandı: {karakter_id} → "
                    f"{os.path.basename(referans)}",
                    "success",
                )

    # --------------------------------------------------------
    # Dil Değişimi
    # --------------------------------------------------------

    def _dil_degisti(self, dil_kodu: str):
        """
        Ayarlar panelinden dil değiştiğinde çağrılır.
        Tüm karakter kartlarının ses listelerini günceller.
        """
        self._karakter_panel.dil_guncelle(dil_kodu)
        self.log(f"Hedef dil değişti: {dil_kodu}")
        self.statusBar().showMessage(f"Hedef dil: {dil_kodu}")

    def _ayarlar_degisti_handler(self):
        """
        Ayarlar panelinde herhangi bir değişiklik olduğunda çağrılır.
        Varsayılan motor değişmişse karakter kartlarını günceller.
        Ayarları config'e yazar (anlık kayıt).
        """
        # Panelden config'e aktar
        try:
            self._ayarlar_panel.config_e_kaydet(self._config)
        except Exception:
            pass

        # Varsayılan motor — yeni eklenen kartlar bu motorla açılsın
        yeni_motor = self._ayarlar_panel._cmb_varsayilan_motor.currentText()
        self._config.ayarla("tts_motorlari.varsayilan", yeni_motor)

        # Config'i dosyaya kaydet
        self._config.kaydet()

    # --------------------------------------------------------
    # İlerleme ve Log
    # --------------------------------------------------------

    def _ilerleme_guncelle(self, yuzde: float, mesaj: str = ""):
        """İlerleme çubuğunu ve durum metnini günceller."""
        self._progress_bar.setValue(int(yuzde))
        self._lbl_ilerleme_yuzde.setText(f"%{yuzde:.1f}")
        if mesaj:
            self._lbl_ilerleme_durum.setText(mesaj)

    def log(self, mesaj: str, seviye: str = "info"):
        """
        Log alanına mesaj ekler.

        Args:
            mesaj: Log mesajı.
            seviye: "info", "warning", "error", "success".
        """
        renk_map = {
            "info": "#d4d4d4",
            "warning": "#FFC107",
            "error": "#F44336",
            "success": "#4CAF50",
        }
        renk = renk_map.get(seviye, "#d4d4d4")
        html = f'<span style="color: {renk};">{mesaj}</span>'
        self._txt_log.append(html)

        # Otomatik aşağı kaydır
        scrollbar = self._txt_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # --------------------------------------------------------
    # Menü Aksiyonları
    # --------------------------------------------------------

    def _ayarlari_kaydet(self):
        """Ayarları JSON dosyasına kaydeder."""
        try:
            self._ayarlar_panel.config_e_kaydet(self._config)
        except Exception:
            pass
        try:
            self._ducking_panel.config_e_kaydet(self._config)
        except Exception:
            pass
        try:
            self._karakter_panel.config_e_kaydet(self._config)
        except Exception:
            pass

        if self._config.kaydet():
            self.log("Ayarlar kaydedildi.", "success")
            self.statusBar().showMessage("Ayarlar kaydedildi.")
        else:
            self.log("Ayarlar kaydedilemedi!", "error")

    def _ayarlari_sifirla(self):
        """Ayarları varsayılana sıfırlar."""
        cevap = QMessageBox.question(
            self,
            "Sıfırla",
            "Tüm ayarlar varsayılana döndürülsün mü?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            self._config.sifirla()
            self._config.kaydet()
            self.log("Ayarlar varsayılana sıfırlandı.", "warning")

    def _hakkinda_goster(self):
        """Hakkında dialogu."""
        QMessageBox.about(
            self,
            "DubSync Pro Hakkında",
            f"<h2>DubSync Pro v{VERSION}</h2>"
            "<p>Film altyazı seslendirme aracı.</p>"
            "<p>SRT/ASS/VTT altyazıları otomatik seslendirir, "
            "orijinal film sesiyle miksler ve video olarak çıktı verir.</p>"
            "<hr>"
            "<p><b>Özellikler:</b></p>"
            "<ul>"
            "<li>Çoklu TTS motor desteği (Edge TTS, XTTS, OpenAI, ElevenLabs)</li>"
            "<li>Otomatik konuşmacı algılama ve karakter-ses eşleme</li>"
            "<li>Akıllı zamanlama: hızlandırma, yavaşlatma, kırpma</li>"
            "<li>Audio ducking (basit + sidechain)</li>"
            "<li>48kHz/24-bit profesyonel ses kalitesi</li>"
            "</ul>"
            "<p>Geliştirici: DubSync Pro Team</p>",
        )

    # --------------------------------------------------------
    # Stil
    # --------------------------------------------------------

    def _stil_uygula(self):
        """Genel uygulama stilini ayarlar."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #fafafa;
                color: #222222;
            }
            QWidget {
                color: #222222;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #333333;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 12px;
                background-color: white;
                color: #222222;
            }
            QLineEdit:read-only {
                background-color: #f5f5f5;
                color: #555555;
            }
            QComboBox {
                color: #222222;
                background-color: #ffffff;
            }
            QSpinBox, QDoubleSpinBox {
                color: #222222;
                background-color: #ffffff;
            }
            QCheckBox {
                color: #333333;
            }
            QTabBar::tab {
                color: #333333;
            }
            QPushButton {
                padding: 6px 14px;
                border: 1px solid #bbb;
                border-radius: 4px;
                font-size: 12px;
                background-color: #f0f0f0;
                color: #333333;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QSplitter::handle {
                background-color: #ddd;
                border-radius: 2px;
            }
            QSplitter::handle:hover {
                background-color: #bbb;
            }
            QStatusBar {
                font-size: 11px;
                color: #666666;
            }
            QScrollArea {
                background-color: #fafafa;
            }
        """)

    # --------------------------------------------------------
    # Pencere Kapatma
    # --------------------------------------------------------

    def closeEvent(self, event):
        """Pencere kapatılırken ayarları kaydet."""
        # Pencere boyutunu kaydet
        self._config.ayarla("genel.pencere_genislik", self.width())
        self._config.ayarla("genel.pencere_yukseklik", self.height())

        # Panellerden ayarları config'e aktar
        try:
            self._ayarlar_panel.config_e_kaydet(self._config)
        except Exception:
            pass
        try:
            self._ducking_panel.config_e_kaydet(self._config)
        except Exception:
            pass
        try:
            self._karakter_panel.config_e_kaydet(self._config)
        except Exception:
            pass

        # Config'i dosyaya yaz
        self._config.kaydet()

        event.accept()

    # --------------------------------------------------------
    # Dış Erişim (diğer modüller için)
    # --------------------------------------------------------

    @property
    def srt_yolu(self) -> str:
        return self._srt_yolu

    @property
    def video_yolu(self) -> str:
        return self._video_yolu

    @property
    def config(self) -> ConfigManager:
        return self._config
