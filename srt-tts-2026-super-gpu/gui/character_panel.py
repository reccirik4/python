# -*- coding: utf-8 -*-
"""
DubSync Pro — Karakter Paneli (character_panel.py)

Otomatik algılanan konuşmacıları listeler, her birine isim,
TTS motoru, ses, cinsiyet, hız ve perde atanmasını sağlar.
Ses önizleme ve klonlama için ses örneği yükleme destekler.
Ses kütüphanesi (dubsync_voices/) entegrasyonu içerir.
"""

import asyncio
import logging
import os
import tempfile
import threading
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QScrollArea,
    QFrame,
    QFileDialog,
    QSlider,
    QMessageBox,
)

from core.config_manager import ConfigManager

logger = logging.getLogger("DubSync.CharacterPanel")


# ============================================================
# Tek Karakter Kartı
# ============================================================

class KarakterKarti(QFrame):
    """
    Tek bir konuşmacıyı temsil eden kart widget'ı.

    İçerir: Speaker ID, isim alanı, motor seçimi, ses seçimi,
    cinsiyet, hız/perde slider'ları, önizleme butonu.
    Ses kütüphanesi entegrasyonu ile klonlama akışı yönetilir.
    """

    degisti = pyqtSignal(str)
    onizleme_istendi = pyqtSignal(str)
    filmden_klonla_istendi = pyqtSignal(str)  # karakter_id
    ses_kutuphanesi_guncellendi = pyqtSignal()  # yeni ses kaydedildi
    # Thread → ana thread iletişimi için klonlama sonuç sinyali
    _klonlama_bitti = pyqtSignal(bool, str, str, str, str)  # (basarili, gecici_wav, referans_yolu, kaynak, hata)

    def __init__(
        self,
        karakter_id: str,
        satir_sayisi: int = 0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._karakter_id = karakter_id
        self._satir_sayisi = satir_sayisi
        self._hedef_dil: str = "tr"
        self._library = None   # VoiceLibrary — dışarıdan set edilir
        self._motor_obj = None  # Klonlama için motor nesnesi

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "KarakterKarti { border: 1px solid #ddd; border-radius: 6px; "
            "background-color: #fff; margin: 2px; padding: 4px; }"
        )

        self._olustur()
        # Thread-safe klonlama sonucu — sinyal ana thread'de işlenir
        self._klonlama_bitti.connect(self._klonlama_sonuc_slot)

    def _olustur(self):
        """Kart içeriğini oluşturur."""
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 6, 8, 6)

        # --- Üst: Speaker ID + satır sayısı ---
        ust = QHBoxLayout()
        lbl_id = QLabel(self._karakter_id)
        lbl_id.setStyleSheet("font-weight: bold; font-size: 12px; color: #333;")
        lbl_sayac = QLabel(f"({self._satir_sayisi} satır)")
        lbl_sayac.setStyleSheet("font-size: 10px; color: #999;")
        ust.addWidget(lbl_id)
        ust.addStretch()
        ust.addWidget(lbl_sayac)
        layout.addLayout(ust)

        # --- İsim ---
        isim_layout = QHBoxLayout()
        isim_layout.setSpacing(4)
        lbl_isim = QLabel("İsim:")
        lbl_isim.setFixedWidth(38)
        lbl_isim.setStyleSheet("font-size: 11px;")
        self._txt_isim = QLineEdit()
        self._txt_isim.setPlaceholderText("Karakter adı")
        self._txt_isim.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self._txt_isim.setMaximumHeight(26)
        self._txt_isim.textChanged.connect(self._degisiklik_bildir)
        isim_layout.addWidget(lbl_isim)
        isim_layout.addWidget(self._txt_isim)
        layout.addLayout(isim_layout)

        # --- Motor ---
        motor_layout = QHBoxLayout()
        motor_layout.setSpacing(4)
        lbl_motor = QLabel("Motor:")
        lbl_motor.setFixedWidth(38)
        lbl_motor.setStyleSheet("font-size: 11px;")
        self._cmb_motor = QComboBox()
        self._cmb_motor.setStyleSheet("font-size: 11px; padding: 2px;")
        self._cmb_motor.setMaximumHeight(26)
        self._cmb_motor.currentIndexChanged.connect(self._motor_degisti)
        motor_layout.addWidget(lbl_motor)
        motor_layout.addWidget(self._cmb_motor)
        layout.addLayout(motor_layout)

        # --- Ses ---
        ses_layout = QHBoxLayout()
        ses_layout.setSpacing(4)
        lbl_ses = QLabel("Ses:")
        lbl_ses.setFixedWidth(38)
        lbl_ses.setStyleSheet("font-size: 11px;")
        self._cmb_ses = QComboBox()
        self._cmb_ses.setStyleSheet("font-size: 11px; padding: 2px;")
        self._cmb_ses.setMaximumHeight(26)
        self._cmb_ses.currentIndexChanged.connect(self._degisiklik_bildir)
        ses_layout.addWidget(lbl_ses)
        ses_layout.addWidget(self._cmb_ses)
        layout.addLayout(ses_layout)

        # --- Cinsiyet ---
        cins_layout = QHBoxLayout()
        cins_layout.setSpacing(4)
        lbl_cins = QLabel("Cins.:")
        lbl_cins.setFixedWidth(38)
        lbl_cins.setStyleSheet("font-size: 11px;")
        self._cmb_cinsiyet = QComboBox()
        self._cmb_cinsiyet.addItems(["erkek", "kadın"])
        self._cmb_cinsiyet.setStyleSheet("font-size: 11px; padding: 2px;")
        self._cmb_cinsiyet.setMaximumHeight(26)
        self._cmb_cinsiyet.currentIndexChanged.connect(self._cinsiyet_degisti)
        cins_layout.addWidget(lbl_cins)
        cins_layout.addWidget(self._cmb_cinsiyet)
        layout.addLayout(cins_layout)

        # --- Hız ---
        hiz_layout = QHBoxLayout()
        hiz_layout.setSpacing(4)
        lbl_hiz = QLabel("Hız:")
        lbl_hiz.setFixedWidth(38)
        lbl_hiz.setStyleSheet("font-size: 11px;")
        self._slider_hiz = QSlider(Qt.Orientation.Horizontal)
        self._slider_hiz.setRange(-50, 50)
        self._slider_hiz.setValue(0)
        self._slider_hiz.setMaximumHeight(20)
        self._lbl_hiz_deger = QLabel("+0%")
        self._lbl_hiz_deger.setFixedWidth(36)
        self._lbl_hiz_deger.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_hiz_deger.setStyleSheet("font-size: 10px; color: #666;")
        self._slider_hiz.valueChanged.connect(self._hiz_degisti)
        hiz_layout.addWidget(lbl_hiz)
        hiz_layout.addWidget(self._slider_hiz)
        hiz_layout.addWidget(self._lbl_hiz_deger)
        layout.addLayout(hiz_layout)

        # --- Perde ---
        perde_layout = QHBoxLayout()
        perde_layout.setSpacing(4)
        lbl_perde = QLabel("Perde:")
        lbl_perde.setFixedWidth(38)
        lbl_perde.setStyleSheet("font-size: 11px;")
        self._slider_perde = QSlider(Qt.Orientation.Horizontal)
        self._slider_perde.setRange(-50, 50)
        self._slider_perde.setValue(0)
        self._slider_perde.setMaximumHeight(20)
        self._lbl_perde_deger = QLabel("+0Hz")
        self._lbl_perde_deger.setFixedWidth(36)
        self._lbl_perde_deger.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_perde_deger.setStyleSheet("font-size: 10px; color: #666;")
        self._slider_perde.valueChanged.connect(self._perde_degisti)
        perde_layout.addWidget(lbl_perde)
        perde_layout.addWidget(self._slider_perde)
        perde_layout.addWidget(self._lbl_perde_deger)
        layout.addLayout(perde_layout)

        # --- Alt butonlar ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self._btn_onizleme = QPushButton("▶ Dinle")
        self._btn_onizleme.setMaximumHeight(26)
        self._btn_onizleme.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; "
            "background-color: #e3f2fd; border: 1px solid #90caf9; border-radius: 3px; }"
            "QPushButton:hover { background-color: #bbdefb; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_onizleme.clicked.connect(
            lambda: self.onizleme_istendi.emit(self._karakter_id)
        )

        self._btn_klonla = QPushButton("🎤 Klonla")
        self._btn_klonla.setMaximumHeight(26)
        self._btn_klonla.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; "
            "background-color: #fce4ec; border: 1px solid #f48fb1; border-radius: 3px; }"
            "QPushButton:hover { background-color: #f8bbd0; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_klonla.clicked.connect(self._klonlama_ses_sec)
        self._btn_klonla.setToolTip("Ses klonlama için referans ses dosyası seç")

        self._btn_filmden = QPushButton("🎬 Filmden")
        self._btn_filmden.setMaximumHeight(26)
        self._btn_filmden.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; "
            "background-color: #e8f5e9; border: 1px solid #81c784; border-radius: 3px; }"
            "QPushButton:hover { background-color: #c8e6c9; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_filmden.clicked.connect(
            lambda: self.filmden_klonla_istendi.emit(self._karakter_id)
        )
        self._btn_filmden.setToolTip("Filmden seçili satırları keserek referans ses oluştur")

        btn_layout.addWidget(self._btn_onizleme)
        btn_layout.addWidget(self._btn_klonla)
        btn_layout.addWidget(self._btn_filmden)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Klonlama durumu etiketi
        self._lbl_klon_durum = QLabel("")
        self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #999;")
        self._lbl_klon_durum.setWordWrap(True)
        self._lbl_klon_durum.hide()
        layout.addWidget(self._lbl_klon_durum)

        # Klonlama yolu (gizli, veri taşımak için)
        self._klon_yolu: str = ""

    # --------------------------------------------------------
    # Sinyal İşleyiciler
    # --------------------------------------------------------

    def _degisiklik_bildir(self):
        self.degisti.emit(self._karakter_id)

    def _motor_degisti(self):
        """Motor değiştiğinde ses listesini günceller."""
        self._ses_listesini_guncelle()
        self._degisiklik_bildir()

    def _cinsiyet_degisti(self):
        """Cinsiyet değiştiğinde Edge TTS ses listesini günceller."""
        motor = self._cmb_motor.currentData() or self._cmb_motor.currentText()
        if motor == "edge_tts":
            self._ses_listesini_guncelle()
        self._degisiklik_bildir()

    def _ses_listesini_guncelle(self, hedef_dil: str = ""):
        """
        Seçili motora göre ses dropdown'ını doldurur.
        XTTS motoru için kütüphanedeki klonlanmış sesleri de ekler.
        """
        motor = self._cmb_motor.currentData() or self._cmb_motor.currentText()
        onceki_ses = self._cmb_ses.currentData() or self._cmb_ses.currentText()

        self._cmb_ses.blockSignals(True)
        self._cmb_ses.clear()

        if motor == "edge_tts":
            self._edge_sesleri_yukle(hedef_dil)

        elif motor == "xtts_v2":
            # Kütüphanedeki klonlanmış sesleri ekle
            self._kutuphaneden_xtts_sesleri_yukle()

        elif motor == "openai":
            self._openai_sesleri_yukle()

        elif motor == "elevenlabs":
            self._cmb_ses.addItem("(API bağlantısı gerekli)", "")

        # Önceki sesi geri seç
        if onceki_ses:
            for i in range(self._cmb_ses.count()):
                if self._cmb_ses.itemData(i) == onceki_ses:
                    self._cmb_ses.setCurrentIndex(i)
                    break

        self._cmb_ses.blockSignals(False)

    def _kutuphaneden_xtts_sesleri_yukle(self):
        """
        XTTS motoru için:
        1. Ses kütüphanesindeki kayıtlı klonları ekle
        2. Eğer klon_yolu varsa ve kütüphanede yoksa da ekle
        """
        # Kütüphanedeki sesler
        if self._library:
            sesler = self._library.sesleri_listele()
            for bilgi in sesler:
                isim = bilgi["isim"]
                tam_yol = bilgi.get("tam_yol", "")
                if tam_yol and os.path.isfile(tam_yol):
                    self._cmb_ses.addItem(f"🎙 {isim}", tam_yol)

        # Mevcut klon_yolu varsa ve listede yoksa ekle
        if self._klon_yolu and os.path.isfile(self._klon_yolu):
            zaten_var = False
            for i in range(self._cmb_ses.count()):
                if self._cmb_ses.itemData(i) == self._klon_yolu:
                    zaten_var = True
                    break
            if not zaten_var:
                dosya_adi = os.path.splitext(os.path.basename(self._klon_yolu))[0]
                self._cmb_ses.addItem(f"🎙 {dosya_adi}", self._klon_yolu)

        # Hiç ses yoksa placeholder
        if self._cmb_ses.count() == 0:
            self._cmb_ses.addItem("(Önce klonlama yapın)", "")

    def _edge_sesleri_yukle(self, hedef_dil: str = ""):
        """Edge TTS seslerini dile göre yükler."""
        from gui.settings_panel import SettingsPanel

        if not hedef_dil:
            hedef_dil = self._hedef_dil or "tr"

        dil_bilgi = SettingsPanel.DILLER.get(hedef_dil)
        if dil_bilgi:
            ad, erkek, kadin = dil_bilgi
            cinsiyet = self._cmb_cinsiyet.currentText()
            if cinsiyet == "kadın":
                self._cmb_ses.addItem(f"♀ {kadin}", kadin)
                self._cmb_ses.addItem(f"♂ {erkek}", erkek)
            else:
                self._cmb_ses.addItem(f"♂ {erkek}", erkek)
                self._cmb_ses.addItem(f"♀ {kadin}", kadin)
        else:
            self._cmb_ses.addItem("♂ tr-TR-AhmetNeural", "tr-TR-AhmetNeural")
            self._cmb_ses.addItem("♀ tr-TR-EmelNeural", "tr-TR-EmelNeural")

    def _openai_sesleri_yukle(self):
        """OpenAI TTS 13 yerleşik sesi yükler."""
        sesler = [
            ("alloy", "Alloy (nötr)"),
            ("ash", "Ash (♂ güçlü)"),
            ("ballad", "Ballad (♀ melodik)"),
            ("coral", "Coral (♀ sıcak)"),
            ("echo", "Echo (♂ derin)"),
            ("fable", "Fable (♂ anlatıcı)"),
            ("onyx", "Onyx (♂ otoriter)"),
            ("nova", "Nova (♀ enerjik)"),
            ("sage", "Sage (♀ sakin)"),
            ("shimmer", "Shimmer (♀ parlak)"),
            ("verse", "Verse (♂ ifadeli)"),
            ("marin", "Marin (♀ doğal) ★"),
            ("cedar", "Cedar (♂ doğal) ★"),
        ]
        for ses_id, gorunen in sesler:
            self._cmb_ses.addItem(gorunen, ses_id)

    def _hiz_degisti(self, deger: int):
        isaret = "+" if deger >= 0 else ""
        self._lbl_hiz_deger.setText(f"{isaret}{deger}%")
        self._degisiklik_bildir()

    def _perde_degisti(self, deger: int):
        isaret = "+" if deger >= 0 else ""
        self._lbl_perde_deger.setText(f"{isaret}{deger}Hz")
        self._degisiklik_bildir()

    # --------------------------------------------------------
    # Klonlama Akışı
    # --------------------------------------------------------

    def _klonlama_ses_sec(self):
        """
        Referans ses dosyası seçer.
        Seçim yapılır yapılmaz klonlama başlar:
        - Dinle butonu inaktif
        - Klonlama tamamlanınca SesCalistirVeKaydetDialog açılır
        """
        yol, _ = QFileDialog.getOpenFileName(
            self, "Referans Ses Dosyası Seç", "",
            "Ses Dosyaları (*.wav *.mp3 *.ogg *.flac);;Tüm Dosyalar (*)",
        )
        if yol and os.path.isfile(yol):
            self._klonlama_baslat(yol, kaynak="dosyadan")

    def _klonlama_baslat(self, referans_yolu: str, kaynak: str = "dosyadan"):
        """
        Referans ses ile klonlama üretimini başlatır.

        Args:
            referans_yolu: Klonlanacak ses dosyası yolu.
            kaynak: "dosyadan" veya "filmden".
        """
        if not referans_yolu or not os.path.isfile(referans_yolu):
            return

        # Motoru kontrol et — sadece XTTS için klonlama
        motor_adi = self._cmb_motor.currentData() or self._cmb_motor.currentText()
        if motor_adi != "xtts_v2":
            # XTTS değilse sadece referans yolunu ata
            self._referans_ata_ve_motoru_ayarla(referans_yolu)
            return

        # Dinle butonunu inaktif yap
        self._btn_onizleme.setEnabled(False)
        self._btn_klonla.setEnabled(False)
        self._btn_filmden.setEnabled(False)
        self._lbl_klon_durum.setText("⏳ Klonlanıyor, lütfen bekleyin...")
        self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #FF9800;")
        self._lbl_klon_durum.show()

        # Arka planda üretim
        t = threading.Thread(
            target=self._klonlama_thread,
            args=(referans_yolu, kaynak),
            daemon=True,
        )
        t.start()

    def _klonlama_thread(self, referans_yolu: str, kaynak: str):
        """Arka planda XTTS ile test sesi üretir."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            motor = self._motor_nesnesini_al()
            if motor is None:
                self._klonlama_sonuc(
                    basarili=False,
                    gecici_wav="",
                    referans_yolu=referans_yolu,
                    kaynak=kaynak,
                    hata="Motor başlatılamadı.",
                )
                loop.close()
                return

            if not motor.hazir:
                try:
                    loop.run_until_complete(motor.baslat())
                except Exception as e:
                    self._klonlama_sonuc(
                        basarili=False,
                        gecici_wav="",
                        referans_yolu=referans_yolu,
                        kaynak=kaynak,
                        hata=str(e),
                    )
                    loop.close()
                    return

            from gui.voice_library_dialog import SesCalistirVeKaydetDialog
            test_cumlesi = SesCalistirVeKaydetDialog._test_cumlesi_sec(
                self._hedef_dil or "tr"
            )

            gecici = os.path.join(
                tempfile.gettempdir(),
                f"dubsync_klon_{self._karakter_id}_{os.getpid()}.wav"
            )

            sonuc = loop.run_until_complete(
                motor.ses_uret(
                    metin=test_cumlesi,
                    ses_id=referans_yolu,
                    cikis_yolu=gecici,
                )
            )
            loop.close()

            self._motor_obj = motor  # Dialog için sakla

            if sonuc.basarili and os.path.isfile(gecici):
                self._klonlama_sonuc(
                    basarili=True,
                    gecici_wav=gecici,
                    referans_yolu=referans_yolu,
                    kaynak=kaynak,
                )
            else:
                self._klonlama_sonuc(
                    basarili=False,
                    gecici_wav="",
                    referans_yolu=referans_yolu,
                    kaynak=kaynak,
                    hata=sonuc.hata_mesaji,
                )

        except Exception as e:
            logger.error("Klonlama thread hatası: %s", e)
            self._klonlama_sonuc(
                basarili=False,
                gecici_wav="",
                referans_yolu=referans_yolu,
                kaynak=kaynak,
                hata=str(e),
            )

    def _klonlama_sonuc(
        self,
        basarili: bool,
        gecici_wav: str,
        referans_yolu: str,
        kaynak: str,
        hata: str = "",
    ):
        """
        Klonlama tamamlandığında thread'den çağrılır.
        pyqtSignal ile ana thread'e iletilir (thread-safe).
        """
        self._klonlama_bitti.emit(basarili, gecici_wav, referans_yolu, kaynak, hata)

    def _klonlama_sonuc_slot(
        self,
        basarili: bool,
        gecici_wav: str,
        referans_yolu: str,
        kaynak: str,
        hata: str,
    ):
        """Ana thread'de klonlama sonucunu işler (sinyal slot'u)."""

        # Butonları geri aç
        self._btn_klonla.setEnabled(True)
        self._btn_filmden.setEnabled(True)

        if not basarili:
            self._btn_onizleme.setEnabled(True)
            self._lbl_klon_durum.setText(f"❌ Klonlama başarısız: {hata[:60]}")
            self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #F44336;")
            return

        # Klonlama başarılı — SesCalistirVeKaydetDialog aç
        if not self._library:
            # Kütüphane yoksa sadece referans ata
            self._btn_onizleme.setEnabled(True)
            self._referans_ata_ve_motoru_ayarla(referans_yolu)
            self._lbl_klon_durum.setText("✅ Referans atandı.")
            self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #4CAF50;")
            return

        from gui.voice_library_dialog import SesCalistirVeKaydetDialog
        dialog = SesCalistirVeKaydetDialog(
            gecici_wav=gecici_wav,
            library=self._library,
            motor=self._motor_obj,
            referans_yolu=referans_yolu,
            dil=self._hedef_dil or "tr",
            parent=self,
        )

        # Dialog kapanınca Dinle butonu aktif
        self._btn_onizleme.setEnabled(True)

        if dialog.exec():
            # Kaydedildi
            kaydedilen_yol = dialog.kaydedilen_yol
            kaydedilen_isim = dialog.kaydedilen_isim
            if kaydedilen_yol:
                self._klon_yolu = kaydedilen_yol
                # Ses listesini güncelle
                self._ses_listesini_guncelle()
                # Yeni sesi seç
                for i in range(self._cmb_ses.count()):
                    if self._cmb_ses.itemData(i) == kaydedilen_yol:
                        self._cmb_ses.setCurrentIndex(i)
                        break
                self._lbl_klon_durum.setText(
                    f"✅ Kaydedildi: {kaydedilen_isim}"
                )
                self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #4CAF50;")
                self._lbl_klon_durum.show()
                self._degisiklik_bildir()
                # Diğer kartlara bildir
                self.ses_kutuphanesi_guncellendi.emit()
        else:
            # İptal — geçici wav'ı referans olarak ata
            self._klon_yolu = gecici_wav
            self._ses_listesini_guncelle()
            self._lbl_klon_durum.setText(
                "⚠️ Kaydedilmedi (geçici). Kaydetmek için tekrar Klonla'ya basın."
            )
            self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #FF9800;")
            self._lbl_klon_durum.show()

    def _motor_nesnesini_al(self):
        """XTTS motor nesnesini oluşturur veya mevcut olanı döndürür."""
        try:
            from engines.xtts_engine import XTTSEngine
            # Mevcut motor nesnesi varsa kullan
            if self._motor_obj and hasattr(self._motor_obj, "hazir"):
                return self._motor_obj
            # Yeni oluştur
            ayarlar = {}
            # Config'e erişim için parent chain'e bak
            parent = self.parent()
            while parent is not None:
                if hasattr(parent, "_config"):
                    cfg = parent._config
                    ayarlar = {
                        "gpu_kullan": cfg.al("tts_motorlari.xtts_v2.gpu_kullan", True),
                        "dil": cfg.al("tts_motorlari.xtts_v2.dil", "tr"),
                    }
                    # Aktif tts_manager'dan al
                    if hasattr(parent, "_tts_manager") and parent._tts_manager:
                        motor = parent._tts_manager._motorlar.get("xtts_v2")
                        if motor:
                            return motor
                    break
                parent = parent.parent() if hasattr(parent, "parent") else None

            return XTTSEngine(ayarlar)
        except Exception as e:
            logger.error("XTTS motor oluşturma hatası: %s", e)
            return None

    # --------------------------------------------------------
    # Veri Okuma / Yazma
    # --------------------------------------------------------

    @property
    def karakter_id(self) -> str:
        return self._karakter_id

    def veri_al(self) -> dict:
        """Karttaki tüm değerleri sözlük olarak döndürür."""
        cinsiyet = "kadin" if self._cmb_cinsiyet.currentIndex() == 1 else "erkek"
        hiz = self._slider_hiz.value()
        perde = self._slider_perde.value()
        isaret_h = "+" if hiz >= 0 else ""
        isaret_p = "+" if perde >= 0 else ""

        ses_id = self._cmb_ses.currentData() or self._cmb_ses.currentText()

        return {
            "isim": self._txt_isim.text().strip(),
            "motor": self._cmb_motor.currentData() or self._cmb_motor.currentText(),
            "ses": ses_id,
            "cinsiyet": cinsiyet,
            "hiz": f"{isaret_h}{hiz}%",
            "perde": f"{isaret_p}{perde}Hz",
            "klon_yolu": self._klon_yolu,
        }

    def veri_yukle(self, veri: dict):
        """Sözlükten kart alanlarını doldurur."""
        self._txt_isim.setText(veri.get("isim", ""))

        cinsiyet = veri.get("cinsiyet", "erkek")
        self._cmb_cinsiyet.setCurrentIndex(1 if cinsiyet == "kadin" else 0)

        hiz_str = veri.get("hiz", "+0%")
        try:
            hiz_val = int(hiz_str.replace("%", "").replace("+", ""))
            self._slider_hiz.setValue(hiz_val)
        except ValueError:
            self._slider_hiz.setValue(0)

        perde_str = veri.get("perde", "+0Hz")
        try:
            perde_val = int(perde_str.replace("Hz", "").replace("+", ""))
            self._slider_perde.setValue(perde_val)
        except ValueError:
            self._slider_perde.setValue(0)

        # Klonlama yolu
        klon_yolu = veri.get("klon_yolu", "")
        if klon_yolu:
            self._klon_yolu = klon_yolu
            if os.path.isfile(klon_yolu):
                self._lbl_klon_durum.setText(
                    f"✅ Klon: {os.path.basename(klon_yolu)}"
                )
                self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #4CAF50;")
                self._lbl_klon_durum.show()

    def referans_ses_ayarla(self, yol: str):
        """
        Klonlama referans ses yolunu ayarlar (CloneDialog'dan çağrılır).
        Filmden klonlama sonrası çağrılır — klonlama başlatır.
        """
        if yol and os.path.isfile(yol):
            motor_adi = self._cmb_motor.currentData() or self._cmb_motor.currentText()
            if motor_adi == "xtts_v2":
                self._klonlama_baslat(yol, kaynak="filmden")
            else:
                self._referans_ata_ve_motoru_ayarla(yol)

    def _referans_ata_ve_motoru_ayarla(self, yol: str):
        """
        Referans ses atanır ve motor otomatik olarak klonlama motoruna çekilir.
        (XTTS dışı motorlar için veya kütüphane yoksa fallback.)
        """
        self._klon_yolu = yol
        self._lbl_klon_durum.setText(f"Referans: {os.path.basename(yol)}")
        self._lbl_klon_durum.setStyleSheet("font-size: 9px; color: #999;")
        self._lbl_klon_durum.show()

        mevcut_motor = self._cmb_motor.currentData() or self._cmb_motor.currentText()

        if mevcut_motor in ("xtts_v2", "elevenlabs"):
            self._ses_listesini_guncelle()
            self._degisiklik_bildir()
            return

        # XTTS-v2 dropdown'da var mı?
        xtts_bulundu = False
        for i in range(self._cmb_motor.count()):
            if self._cmb_motor.itemData(i) == "xtts_v2":
                self._cmb_motor.setCurrentIndex(i)
                xtts_bulundu = True
                break

        if not xtts_bulundu:
            for i in range(self._cmb_motor.count()):
                if self._cmb_motor.itemData(i) == "elevenlabs":
                    self._cmb_motor.setCurrentIndex(i)
                    break

        self._ses_listesini_guncelle()

        for i in range(self._cmb_ses.count()):
            if self._cmb_ses.itemData(i) == yol:
                self._cmb_ses.setCurrentIndex(i)
                break

        self._degisiklik_bildir()

    def motorlari_ayarla(self, motor_listesi: list[tuple[str, str]]):
        """Motor dropdown'ını doldurur."""
        self._cmb_motor.blockSignals(True)
        self._cmb_motor.clear()
        for motor_adi, gorunen_ad in motor_listesi:
            self._cmb_motor.addItem(gorunen_ad, motor_adi)
        self._cmb_motor.blockSignals(False)

    def motor_sec(self, motor_adi: str):
        """Belirtilen motoru seçili yapar."""
        for i in range(self._cmb_motor.count()):
            if self._cmb_motor.itemData(i) == motor_adi:
                self._cmb_motor.setCurrentIndex(i)
                return

    def sesleri_ayarla(self, ses_listesi: list[tuple[str, str]]):
        """Ses dropdown'ını doldurur."""
        self._cmb_ses.blockSignals(True)
        self._cmb_ses.clear()
        for ses_id, gorunen_ad in ses_listesi:
            self._cmb_ses.addItem(gorunen_ad, ses_id)
        self._cmb_ses.blockSignals(False)

    def ses_sec(self, ses_id: str):
        """Belirtilen sesi seçili yapar."""
        for i in range(self._cmb_ses.count()):
            if self._cmb_ses.itemData(i) == ses_id:
                self._cmb_ses.setCurrentIndex(i)
                return

    def library_ayarla(self, library):
        """VoiceLibrary nesnesini atar ve ses listesini günceller."""
        self._library = library
        motor_adi = self._cmb_motor.currentData() or self._cmb_motor.currentText()
        if motor_adi == "xtts_v2":
            self._ses_listesini_guncelle()

    def kutuphaneden_sesleri_yenile(self):
        """Ses kütüphanesi güncellenince dropdown'ı yeniler."""
        motor_adi = self._cmb_motor.currentData() or self._cmb_motor.currentText()
        if motor_adi == "xtts_v2":
            onceki = self._cmb_ses.currentData()
            self._ses_listesini_guncelle()
            if onceki:
                self.ses_sec(onceki)


# ============================================================
# Karakter Paneli (Ana Widget)
# ============================================================

class CharacterPanel(QWidget):
    """
    Tüm karakterleri listeleyen scrollable panel.

    SRT dosyası yüklendiğinde otomatik olarak konuşmacıları algılar,
    her biri için bir KarakterKarti oluşturur.
    """

    karakter_degisti = pyqtSignal(str)
    onizleme_istendi = pyqtSignal(str)
    filmden_klonla_istendi = pyqtSignal(str)  # karakter_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._kartlar: dict[str, KarakterKarti] = {}
        self._library = None  # VoiceLibrary

        self.setMinimumWidth(240)
        self.setMaximumWidth(350)

        self._olustur()

    def _olustur(self):
        """Panel yapısını oluşturur."""
        ana_layout = QVBoxLayout(self)
        ana_layout.setContentsMargins(0, 0, 0, 0)
        ana_layout.setSpacing(4)

        baslik = QLabel("🎭 Karakterler")
        baslik.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        ana_layout.addWidget(baslik)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._konteyner = QWidget()
        self._kart_layout = QVBoxLayout(self._konteyner)
        self._kart_layout.setSpacing(6)
        self._kart_layout.setContentsMargins(4, 4, 4, 4)
        self._kart_layout.addStretch()

        self._scroll.setWidget(self._konteyner)
        ana_layout.addWidget(self._scroll, stretch=1)

        self._lbl_toplam = QLabel("Henüz SRT yüklenmedi.")
        self._lbl_toplam.setStyleSheet("font-size: 10px; color: #999; padding: 2px;")
        ana_layout.addWidget(self._lbl_toplam)

    # --------------------------------------------------------
    # Konuşmacı Yükleme
    # --------------------------------------------------------

    # 4 motor sabit listesi
    MOTOR_LISTESI = [
        ("edge_tts", "Edge TTS"),
        ("xtts_v2", "XTTS-v2 (Klonlama)"),
        ("openai", "OpenAI TTS"),
        ("elevenlabs", "ElevenLabs"),
    ]

    def library_ayarla(self, library):
        """
        VoiceLibrary nesnesini panele ve tüm kartlara atar.

        Args:
            library: VoiceLibrary nesnesi.
        """
        self._library = library
        for kart in self._kartlar.values():
            kart.library_ayarla(library)

    def konusmacilari_yukle(
        self,
        konusmacilar: dict[str, dict],
        config: Optional[ConfigManager] = None,
        motor_listesi: Optional[list[tuple[str, str]]] = None,
    ):
        """Algılanan konuşmacılardan karakter kartları oluşturur."""
        self.temizle()

        if motor_listesi is None:
            motor_listesi = self.MOTOR_LISTESI

        # Hedef dili config'den oku
        hedef_dil = "tr"
        varsayilan_motor = "edge_tts"
        if config:
            hedef_dil = config.al("genel.hedef_dil", "tr")
            varsayilan_motor = config.al("tts_motorlari.varsayilan", "edge_tts")

        for karakter_id, bilgi in konusmacilar.items():
            satir_sayisi = bilgi.get("sayi", 0)
            kart = KarakterKarti(karakter_id, satir_sayisi, parent=self._konteyner)
            kart._hedef_dil = hedef_dil

            # Library ata
            if self._library:
                kart._library = self._library

            kart.motorlari_ayarla(motor_listesi)

            if config:
                mevcut = config.karakter_al(karakter_id)
                if mevcut:
                    kart.veri_yukle(mevcut)
                    kart.motor_sec(mevcut.get("motor", ""))
                else:
                    kart.motor_sec(varsayilan_motor)

            kart.degisti.connect(self._kart_degisti)
            kart.onizleme_istendi.connect(self.onizleme_istendi.emit)
            kart.filmden_klonla_istendi.connect(self.filmden_klonla_istendi.emit)
            # Kütüphane güncellenince tüm kartları yenile
            kart.ses_kutuphanesi_guncellendi.connect(self._tum_kartlari_yenile)

            self._kart_layout.insertWidget(self._kart_layout.count() - 1, kart)
            self._kartlar[karakter_id] = kart

            # Ses listesini başlat
            kart._ses_listesini_guncelle(hedef_dil)

            # Config'deki sesi geri seç
            if config:
                mevcut = config.karakter_al(karakter_id)
                if mevcut and mevcut.get("ses"):
                    kart.ses_sec(mevcut.get("ses", ""))

        toplam_satir = sum(b.get("sayi", 0) for b in konusmacilar.values())
        self._lbl_toplam.setText(f"{len(konusmacilar)} karakter, {toplam_satir} satır")

        logger.info("Karakter paneli yüklendi: %d karakter", len(konusmacilar))

    def _tum_kartlari_yenile(self):
        """Ses kütüphanesi güncellenince tüm XTTS kartlarının dropdown'ını yeniler."""
        for kart in self._kartlar.values():
            kart.kutuphaneden_sesleri_yenile()

    def sesleri_guncelle(self, motor_adi: str, ses_listesi: list[tuple[str, str]]):
        """Belirtilen motoru kullanan kartların ses listesini günceller."""
        for kart in self._kartlar.values():
            if kart._cmb_motor.currentData() == motor_adi:
                kart.sesleri_ayarla(ses_listesi)

    def dil_guncelle(self, hedef_dil: str):
        """Tüm kartların hedef dilini günceller ve ses listelerini yeniler."""
        for kart in self._kartlar.values():
            kart._hedef_dil = hedef_dil
            kart._ses_listesini_guncelle(hedef_dil)

    # --------------------------------------------------------
    # Veri Toplama
    # --------------------------------------------------------

    def tum_verileri_al(self) -> dict[str, dict]:
        """Tüm kartların verilerini toplar."""
        return {kid: kart.veri_al() for kid, kart in self._kartlar.items()}

    def config_e_kaydet(self, config: ConfigManager):
        """Tüm karakter verilerini ConfigManager'a kaydeder."""
        for karakter_id, kart in self._kartlar.items():
            veri = kart.veri_al()
            config.karakter_ekle(
                karakter_id=karakter_id,
                isim=veri.get("isim", ""),
                motor=veri.get("motor", ""),
                ses=veri.get("ses", ""),
                cinsiyet=veri.get("cinsiyet", "erkek"),
                hiz=veri.get("hiz", "+0%"),
                perde=veri.get("perde", "+0Hz"),
                klon_yolu=veri.get("klon_yolu", ""),
            )

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    def kart_al(self, karakter_id: str) -> Optional[KarakterKarti]:
        return self._kartlar.get(karakter_id)

    def temizle(self):
        """Tüm kartları kaldırır."""
        for kart in self._kartlar.values():
            kart.setParent(None)
            kart.deleteLater()
        self._kartlar.clear()
        self._lbl_toplam.setText("Henüz SRT yüklenmedi.")

    @property
    def karakter_sayisi(self) -> int:
        return len(self._kartlar)

    def _kart_degisti(self, karakter_id: str):
        self.karakter_degisti.emit(karakter_id)
