# -*- coding: utf-8 -*-
"""
DubSync Pro — Ducking Paneli (ducking_panel.py)

Audio ducking yöntemi seçimi ve parametrelerini ayarlar.
Basit volume ducking ve FFmpeg sidechain ducking destekler.
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QSlider,
    QGroupBox,
    QFrame,
    QStackedWidget,
)

from core.config_manager import ConfigManager

logger = logging.getLogger("DubSync.DuckingPanel")


class DuckingPanel(QWidget):
    """
    Audio ducking ayarları paneli.

    İki yöntem:
    1. Basit: Volume envelope ile altyazı zamanlarına göre ducking
    2. Sidechain: FFmpeg sidechaincompress filtresi

    Her yöntemin kendine özel parametreleri var, yöntem
    değişince ilgili parametreler gösterilir.
    """

    ayarlar_degisti = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._olustur()

    def _olustur(self):
        """Panel yapısını oluşturur."""
        ana_layout = QVBoxLayout(self)
        ana_layout.setContentsMargins(0, 0, 0, 0)
        ana_layout.setSpacing(4)

        baslik = QLabel("🔊 Ducking")
        baslik.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        ana_layout.addWidget(baslik)

        # --- Genel ayarlar ---
        grp_genel = QGroupBox("Genel")
        grp_genel.setStyleSheet("QGroupBox { font-size: 11px; }")
        fl_genel = QFormLayout(grp_genel)
        fl_genel.setSpacing(4)

        self._chk_aktif = QCheckBox("Ducking aktif")
        self._chk_aktif.setChecked(True)
        self._chk_aktif.setToolTip(
            "Kapalıyken orijinal ses değiştirilmez, sadece TTS eklenir"
        )
        self._chk_aktif.stateChanged.connect(self._aktiflik_degisti)
        fl_genel.addRow(self._chk_aktif)

        self._cmb_yontem = QComboBox()
        self._cmb_yontem.addItem("Basit (Volume Envelope)", "basit")
        self._cmb_yontem.addItem("Sidechain (FFmpeg)", "sidechain")
        self._cmb_yontem.setStyleSheet("font-size: 11px;")
        self._cmb_yontem.setToolTip(
            "Basit: Altyazı zamanlarına göre ses kısar\n"
            "Sidechain: TTS sinyaline göre otomatik kısar"
        )
        self._cmb_yontem.currentIndexChanged.connect(self._yontem_degisti)
        fl_genel.addRow("Yöntem:", self._cmb_yontem)

        ana_layout.addWidget(grp_genel)

        # --- Yönteme göre değişen parametreler ---
        self._stacked = QStackedWidget()
        self._stacked.addWidget(self._basit_parametreler_olustur())   # index 0
        self._stacked.addWidget(self._sidechain_parametreler_olustur())  # index 1
        ana_layout.addWidget(self._stacked)

        # --- Seviye gösterimi ---
        self._seviye_gosterim_olustur(ana_layout)

        ana_layout.addStretch()

    # --------------------------------------------------------
    # Basit Ducking Parametreleri
    # --------------------------------------------------------

    def _basit_parametreler_olustur(self) -> QGroupBox:
        """Basit volume ducking parametreleri."""
        grp = QGroupBox("Basit Ducking Parametreleri")
        grp.setStyleSheet("QGroupBox { font-size: 11px; }")
        fl = QFormLayout(grp)
        fl.setSpacing(4)

        # Duck seviyesi (dB)
        self._spn_duck_db = QSpinBox()
        self._spn_duck_db.setRange(-40, 0)
        self._spn_duck_db.setValue(-15)
        self._spn_duck_db.setSuffix(" dB")
        self._spn_duck_db.setStyleSheet("font-size: 11px;")
        self._spn_duck_db.setToolTip(
            "Diyalog sırasında orijinal ses ne kadar kısılsın?\n"
            "-15 dB = %18 seviyeye düşürür\n"
            "-20 dB = %10 seviyeye düşürür\n"
            "0 dB = kısma yok"
        )
        self._spn_duck_db.valueChanged.connect(self._seviye_guncelle)
        fl.addRow("Kısma seviyesi:", self._spn_duck_db)

        # Attack
        self._spn_attack = QSpinBox()
        self._spn_attack.setRange(10, 2000)
        self._spn_attack.setValue(200)
        self._spn_attack.setSuffix(" ms")
        self._spn_attack.setSingleStep(50)
        self._spn_attack.setStyleSheet("font-size: 11px;")
        self._spn_attack.setToolTip(
            "Kısma başlangıç geçiş süresi.\n"
            "Kısa = hızlı düşüş, uzun = yumuşak geçiş"
        )
        self._spn_attack.valueChanged.connect(self._degisiklik)
        fl.addRow("Attack:", self._spn_attack)

        # Release
        self._spn_release = QSpinBox()
        self._spn_release.setRange(50, 5000)
        self._spn_release.setValue(500)
        self._spn_release.setSuffix(" ms")
        self._spn_release.setSingleStep(50)
        self._spn_release.setStyleSheet("font-size: 11px;")
        self._spn_release.setToolTip(
            "Kısma bitiş geçiş süresi.\n"
            "Kısa = hızlı yükseliş, uzun = yumuşak dönüş"
        )
        self._spn_release.valueChanged.connect(self._degisiklik)
        fl.addRow("Release:", self._spn_release)

        # Ön ducking
        self._spn_on_duck = QSpinBox()
        self._spn_on_duck.setRange(0, 1000)
        self._spn_on_duck.setValue(150)
        self._spn_on_duck.setSuffix(" ms")
        self._spn_on_duck.setSingleStep(50)
        self._spn_on_duck.setStyleSheet("font-size: 11px;")
        self._spn_on_duck.setToolTip(
            "Diyalogdan kaç ms önce kısmaya başlansın?\n"
            "150ms iyi bir değer — dinleyici hazırlıklı olur"
        )
        self._spn_on_duck.valueChanged.connect(self._degisiklik)
        fl.addRow("Ön kısma:", self._spn_on_duck)

        return grp

    # --------------------------------------------------------
    # Sidechain Ducking Parametreleri
    # --------------------------------------------------------

    def _sidechain_parametreler_olustur(self) -> QGroupBox:
        """FFmpeg sidechain parametreleri."""
        grp = QGroupBox("Sidechain Parametreleri")
        grp.setStyleSheet("QGroupBox { font-size: 11px; }")
        fl = QFormLayout(grp)
        fl.setSpacing(4)

        # Threshold
        self._spn_sc_threshold = QDoubleSpinBox()
        self._spn_sc_threshold.setRange(0.001, 1.0)
        self._spn_sc_threshold.setSingleStep(0.005)
        self._spn_sc_threshold.setValue(0.02)
        self._spn_sc_threshold.setDecimals(3)
        self._spn_sc_threshold.setStyleSheet("font-size: 11px;")
        self._spn_sc_threshold.setToolTip(
            "TTS sinyalinin bu seviyeyi geçmesi ducking'i tetikler.\n"
            "Düşük = daha hassas, yüksek = sadece güçlü sinyallerde"
        )
        self._spn_sc_threshold.valueChanged.connect(self._degisiklik)
        fl.addRow("Threshold:", self._spn_sc_threshold)

        # Ratio
        self._spn_sc_ratio = QSpinBox()
        self._spn_sc_ratio.setRange(1, 20)
        self._spn_sc_ratio.setValue(4)
        self._spn_sc_ratio.setStyleSheet("font-size: 11px;")
        self._spn_sc_ratio.setToolTip(
            "Sıkıştırma oranı.\n"
            "4 = her 4 dB aşımda 1 dB geçer\n"
            "Yüksek = daha sert kısma"
        )
        self._spn_sc_ratio.valueChanged.connect(self._degisiklik)
        fl.addRow("Ratio:", self._spn_sc_ratio)

        # Sidechain attack
        self._spn_sc_attack = QSpinBox()
        self._spn_sc_attack.setRange(1, 2000)
        self._spn_sc_attack.setValue(200)
        self._spn_sc_attack.setSuffix(" ms")
        self._spn_sc_attack.setStyleSheet("font-size: 11px;")
        self._spn_sc_attack.valueChanged.connect(self._degisiklik)
        fl.addRow("Attack:", self._spn_sc_attack)

        # Sidechain release
        self._spn_sc_release = QSpinBox()
        self._spn_sc_release.setRange(50, 5000)
        self._spn_sc_release.setValue(1000)
        self._spn_sc_release.setSuffix(" ms")
        self._spn_sc_release.setStyleSheet("font-size: 11px;")
        self._spn_sc_release.valueChanged.connect(self._degisiklik)
        fl.addRow("Release:", self._spn_sc_release)

        # FFmpeg bilgi notu
        lbl_not = QLabel(
            "ℹ Sidechain yöntemi FFmpeg'in sidechaincompress\n"
            "filtresini kullanır. FFmpeg yüklü olmalıdır."
        )
        lbl_not.setStyleSheet("font-size: 9px; color: #999; padding: 4px;")
        lbl_not.setWordWrap(True)
        fl.addRow(lbl_not)

        return grp

    # --------------------------------------------------------
    # Seviye Gösterimi
    # --------------------------------------------------------

    def _seviye_gosterim_olustur(self, parent_layout: QVBoxLayout):
        """dB seviye bilgisini görsel olarak gösterir."""
        grp = QGroupBox("Seviye Önizleme")
        grp.setStyleSheet("QGroupBox { font-size: 11px; }")
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)

        # Orijinal ses seviyesi çubuğu
        lbl_orj = QLabel("Orijinal ses:")
        lbl_orj.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(lbl_orj)

        self._bar_orijinal = QFrame()
        self._bar_orijinal.setFixedHeight(12)
        self._bar_orijinal.setStyleSheet(
            "background-color: #4CAF50; border-radius: 3px;"
        )
        layout.addWidget(self._bar_orijinal)

        # Kısılmış ses seviyesi çubuğu
        lbl_duck = QLabel("Diyalog sırasında:")
        lbl_duck.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(lbl_duck)

        self._bar_ducked = QFrame()
        self._bar_ducked.setFixedHeight(12)
        self._bar_ducked.setStyleSheet(
            "background-color: #FF9800; border-radius: 3px;"
        )
        layout.addWidget(self._bar_ducked)

        # Yüzde bilgisi
        self._lbl_seviye_bilgi = QLabel("Diyalog sırasında orijinal ses: %18 seviyeye düşer (-15 dB)")
        self._lbl_seviye_bilgi.setStyleSheet("font-size: 10px; color: #888;")
        self._lbl_seviye_bilgi.setWordWrap(True)
        layout.addWidget(self._lbl_seviye_bilgi)

        parent_layout.addWidget(grp)

        # İlk görsel güncelleme
        self._seviye_guncelle()

    def _seviye_guncelle(self):
        """Seviye çubuklarını ve bilgi metnini günceller."""
        db = self._spn_duck_db.value()
        yuzde = round(10 ** (db / 20) * 100)

        # Çubuk genişliğini ayarla
        max_genislik = 200  # piksel
        ducked_genislik = max(4, int(max_genislik * yuzde / 100))

        self._bar_orijinal.setFixedWidth(max_genislik)
        self._bar_ducked.setFixedWidth(ducked_genislik)

        # Rengi seviyeye göre ayarla
        if yuzde > 50:
            renk = "#FFC107"  # Sarı - hafif kısma
        elif yuzde > 20:
            renk = "#FF9800"  # Turuncu - orta kısma
        else:
            renk = "#F44336"  # Kırmızı - sert kısma

        self._bar_ducked.setStyleSheet(
            f"background-color: {renk}; border-radius: 3px;"
        )

        self._lbl_seviye_bilgi.setText(
            f"Diyalog sırasında orijinal ses: %{yuzde} seviyeye düşer ({db} dB)"
        )

        self._degisiklik()

    # --------------------------------------------------------
    # Yöntem Değişimi
    # --------------------------------------------------------

    def _yontem_degisti(self, index: int):
        """Yöntem değişince ilgili parametre panelini gösterir."""
        self._stacked.setCurrentIndex(index)
        self._degisiklik()

    def _aktiflik_degisti(self, durum: int):
        """Ducking aktif/pasif durumu."""
        aktif = self._chk_aktif.isChecked()
        self._cmb_yontem.setEnabled(aktif)
        self._stacked.setEnabled(aktif)
        self._degisiklik()

    # --------------------------------------------------------
    # Config Senkronizasyonu
    # --------------------------------------------------------

    def config_yukle(self, config: ConfigManager):
        """Config'den ducking ayarlarını yükler."""
        self._chk_aktif.setChecked(config.al("ducking.aktif", True))

        yontem = config.al("ducking.yontem", "basit")
        idx = 0 if yontem == "basit" else 1
        self._cmb_yontem.setCurrentIndex(idx)

        # Basit parametreler
        self._spn_duck_db.setValue(config.al("ducking.duck_seviye_db", -15))
        self._spn_attack.setValue(config.al("ducking.attack_ms", 200))
        self._spn_release.setValue(config.al("ducking.release_ms", 500))
        self._spn_on_duck.setValue(config.al("ducking.on_duck_ms", 150))

        # Sidechain parametreler
        self._spn_sc_threshold.setValue(config.al("ducking.sidechain.threshold", 0.02))
        self._spn_sc_ratio.setValue(config.al("ducking.sidechain.ratio", 4))
        self._spn_sc_attack.setValue(config.al("ducking.sidechain.attack", 200))
        self._spn_sc_release.setValue(config.al("ducking.sidechain.release", 1000))

        self._seviye_guncelle()

    def config_e_kaydet(self, config: ConfigManager):
        """Ducking ayarlarını config'e yazar."""
        config.ayarla("ducking.aktif", self._chk_aktif.isChecked())

        yontem = self._cmb_yontem.currentData() or "basit"
        config.ayarla("ducking.yontem", yontem)

        # Basit
        config.ayarla("ducking.duck_seviye_db", self._spn_duck_db.value())
        config.ayarla("ducking.attack_ms", self._spn_attack.value())
        config.ayarla("ducking.release_ms", self._spn_release.value())
        config.ayarla("ducking.on_duck_ms", self._spn_on_duck.value())

        # Sidechain
        config.ayarla("ducking.sidechain.threshold", self._spn_sc_threshold.value())
        config.ayarla("ducking.sidechain.ratio", self._spn_sc_ratio.value())
        config.ayarla("ducking.sidechain.attack", self._spn_sc_attack.value())
        config.ayarla("ducking.sidechain.release", self._spn_sc_release.value())

    # --------------------------------------------------------
    # Sinyal
    # --------------------------------------------------------

    def _degisiklik(self):
        self.ayarlar_degisti.emit()
