# -*- coding: utf-8 -*-
"""
DubSync Pro — Önizleme Oynatıcı (preview_player.py)

Tek bir altyazı satırının seslendirilmiş halini oynatır.
Oynat/durdur kontrolü, süre gösterimi ve basit dalga formu
gösterir. subprocess ile platformdan bağımsız ses çalma.
"""

import logging
import os
import subprocess
import sys
import threading
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QFrame,
    QProgressBar,
)

logger = logging.getLogger("DubSync.PreviewPlayer")


class PreviewPlayer(QWidget):
    """
    Ses dosyası önizleme oynatıcı.

    Platformdan bağımsız ses çalma:
    - Windows: powershell SoundPlayer veya ffplay
    - Linux/macOS: ffplay veya aplay

    Özellikler:
    - Oynat / Durdur / Tekrar oynat
    - Süre gösterimi
    - Satır bilgisi (karakter, metin)
    - Basit ilerleme çubuğu
    """

    # Sinyaller
    oynatma_basladi = pyqtSignal(str)    # dosya_yolu
    oynatma_bitti = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mevcut_dosya: str = ""
        self._mevcut_sure_ms: int = 0
        self._oynuyor: bool = False
        self._oynatma_sureci: Optional[subprocess.Popen] = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._timer_tik)
        self._gecen_ms: int = 0

        self._olustur()

    def _olustur(self):
        """Widget yapısını oluşturur."""
        ana_layout = QVBoxLayout(self)
        ana_layout.setContentsMargins(0, 0, 0, 0)
        ana_layout.setSpacing(4)

        baslik = QLabel("🎧 Önizleme")
        baslik.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        ana_layout.addWidget(baslik)

        # İçerik çerçevesi
        cerceve = QFrame()
        cerceve.setFrameShape(QFrame.Shape.StyledPanel)
        cerceve.setStyleSheet(
            "QFrame { border: 1px solid #ddd; border-radius: 6px; "
            "background-color: #fff; padding: 6px; }"
        )
        ic_layout = QVBoxLayout(cerceve)
        ic_layout.setSpacing(4)
        ic_layout.setContentsMargins(8, 6, 8, 6)

        # Satır bilgisi
        self._lbl_karakter = QLabel("—")
        self._lbl_karakter.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #333;"
        )
        ic_layout.addWidget(self._lbl_karakter)

        self._lbl_metin = QLabel("Bir satır seçin veya çift tıklayın")
        self._lbl_metin.setStyleSheet("font-size: 10px; color: #666;")
        self._lbl_metin.setWordWrap(True)
        self._lbl_metin.setMaximumHeight(40)
        ic_layout.addWidget(self._lbl_metin)

        # İlerleme çubuğu
        self._progress = QProgressBar()
        self._progress.setMinimum(0)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { border: none; border-radius: 4px; "
            "background-color: #e0e0e0; }"
            "QProgressBar::chunk { border-radius: 4px; "
            "background-color: #2196F3; }"
        )
        ic_layout.addWidget(self._progress)

        # Kontrol satırı
        kontrol = QHBoxLayout()
        kontrol.setSpacing(6)

        self._btn_oynat = QPushButton("▶ Oynat")
        self._btn_oynat.setFixedHeight(28)
        self._btn_oynat.setMinimumWidth(80)
        self._btn_oynat.setStyleSheet(
            "QPushButton { font-size: 11px; font-weight: bold; "
            "background-color: #e3f2fd; border: 1px solid #90caf9; "
            "border-radius: 4px; padding: 2px 10px; }"
            "QPushButton:hover { background-color: #bbdefb; }"
            "QPushButton:disabled { background-color: #eee; color: #aaa; }"
        )
        self._btn_oynat.setEnabled(False)
        self._btn_oynat.clicked.connect(self._oynat_durdur)
        kontrol.addWidget(self._btn_oynat)

        self._btn_tekrar = QPushButton("🔄")
        self._btn_tekrar.setFixedSize(28, 28)
        self._btn_tekrar.setToolTip("Baştan oynat")
        self._btn_tekrar.setStyleSheet(
            "QPushButton { font-size: 13px; border: 1px solid #ddd; "
            "border-radius: 4px; background-color: #f5f5f5; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self._btn_tekrar.setEnabled(False)
        self._btn_tekrar.clicked.connect(self._bastan_oynat)
        kontrol.addWidget(self._btn_tekrar)

        kontrol.addStretch()

        # Süre etiketi
        self._lbl_sure = QLabel("0:00 / 0:00")
        self._lbl_sure.setStyleSheet("font-size: 10px; color: #999;")
        self._lbl_sure.setAlignment(Qt.AlignmentFlag.AlignRight)
        kontrol.addWidget(self._lbl_sure)

        ic_layout.addLayout(kontrol)

        # Durum etiketi
        self._lbl_durum = QLabel("")
        self._lbl_durum.setStyleSheet("font-size: 9px; color: #aaa;")
        ic_layout.addWidget(self._lbl_durum)

        ana_layout.addWidget(cerceve)

    # --------------------------------------------------------
    # Dosya Yükleme
    # --------------------------------------------------------

    def dosya_yukle(
        self,
        dosya_yolu: str,
        karakter: str = "",
        metin: str = "",
        sure_ms: int = 0,
    ):
        """
        Önizlenecek ses dosyasını yükler.

        Args:
            dosya_yolu: WAV/MP3 ses dosya yolu.
            karakter: Konuşmacı adı/ID.
            metin: Altyazı metni.
            sure_ms: Ses süresi (ms). 0 ise dosyadan hesaplanır.
        """
        self.durdur()

        self._mevcut_dosya = dosya_yolu
        self._gecen_ms = 0

        # Karakter ve metin bilgisi
        self._lbl_karakter.setText(karakter or "—")

        gosterim_metin = metin if len(metin) <= 80 else metin[:77] + "..."
        self._lbl_metin.setText(gosterim_metin or "—")

        # Süreyi hesapla
        if sure_ms > 0:
            self._mevcut_sure_ms = sure_ms
        else:
            self._mevcut_sure_ms = self._sure_hesapla(dosya_yolu)

        # Süre gösterimi
        toplam_str = self._ms_to_str(self._mevcut_sure_ms)
        self._lbl_sure.setText(f"0:00 / {toplam_str}")

        # İlerlemeyi sıfırla
        self._progress.setValue(0)

        # Butonları aktif et
        dosya_var = os.path.isfile(dosya_yolu)
        self._btn_oynat.setEnabled(dosya_var)
        self._btn_tekrar.setEnabled(dosya_var)

        if dosya_var:
            self._lbl_durum.setText(f"Hazır: {os.path.basename(dosya_yolu)}")
        else:
            self._lbl_durum.setText("Dosya bulunamadı!")
            self._lbl_durum.setStyleSheet("font-size: 9px; color: #F44336;")

    # --------------------------------------------------------
    # Oynatma Kontrolü
    # --------------------------------------------------------

    def _oynat_durdur(self):
        """Oynat/Durdur toggle."""
        if self._oynuyor:
            self.durdur()
        else:
            self._oynat()

    def _oynat(self):
        """Ses dosyasını çalar."""
        if not self._mevcut_dosya or not os.path.isfile(self._mevcut_dosya):
            return

        self._oynuyor = True
        self._btn_oynat.setText("⏸ Durdur")
        self._lbl_durum.setText("Oynatılıyor...")
        self._lbl_durum.setStyleSheet("font-size: 9px; color: #4CAF50;")

        # Platforma göre ses çalma
        self._oynatma_sureci = self._ses_oynat_subprocess(self._mevcut_dosya)

        # Timer başlat (ilerleme için)
        self._gecen_ms = 0
        self._timer.start()

        self.oynatma_basladi.emit(self._mevcut_dosya)

    def durdur(self):
        """Oynatmayı durdurur."""
        self._oynuyor = False
        self._timer.stop()
        self._btn_oynat.setText("▶ Oynat")

        # Subprocess'i sonlandır
        if self._oynatma_sureci and self._oynatma_sureci.poll() is None:
            try:
                self._oynatma_sureci.terminate()
                self._oynatma_sureci.wait(timeout=2)
            except Exception:
                try:
                    self._oynatma_sureci.kill()
                except Exception:
                    pass
        self._oynatma_sureci = None

        self._lbl_durum.setText("Durduruldu.")
        self._lbl_durum.setStyleSheet("font-size: 9px; color: #aaa;")

    def _bastan_oynat(self):
        """Dosyayı baştan oynatır."""
        self.durdur()
        self._progress.setValue(0)
        self._gecen_ms = 0
        self._oynat()

    # --------------------------------------------------------
    # Subprocess Ses Çalma
    # --------------------------------------------------------

    @staticmethod
    def _ses_oynat_subprocess(dosya_yolu: str) -> Optional[subprocess.Popen]:
        """
        Platforma göre ses dosyasını çalar.

        Windows: ffplay (sessiz mod)
        Linux: ffplay veya aplay
        macOS: ffplay veya afplay
        """
        try:
            if sys.platform == "win32":
                # Önce ffplay dene
                cmd = [
                    "ffplay", "-nodisp", "-autoexit",
                    "-loglevel", "quiet", dosya_yolu,
                ]
            elif sys.platform == "darwin":
                cmd = ["afplay", dosya_yolu]
            else:
                cmd = [
                    "ffplay", "-nodisp", "-autoexit",
                    "-loglevel", "quiet", dosya_yolu,
                ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32"
                    else 0
                ),
            )
            return proc

        except FileNotFoundError:
            logger.warning(
                "Ses oynatıcı bulunamadı (ffplay/afplay). "
                "FFmpeg kurulumunu kontrol edin."
            )
            # Windows fallback: powershell
            if sys.platform == "win32":
                try:
                    ps_cmd = (
                        f"(New-Object Media.SoundPlayer '{dosya_yolu}').PlaySync()"
                    )
                    proc = subprocess.Popen(
                        ["powershell", "-Command", ps_cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    return proc
                except Exception:
                    pass
            return None

        except Exception as e:
            logger.error("Ses çalma hatası: %s", e)
            return None

    # --------------------------------------------------------
    # Timer / İlerleme
    # --------------------------------------------------------

    def _timer_tik(self):
        """100ms aralıkla çağrılır, ilerlemeyi günceller."""
        if not self._oynuyor:
            self._timer.stop()
            return

        # Subprocess bitti mi kontrol et
        if self._oynatma_sureci and self._oynatma_sureci.poll() is not None:
            self._oynatma_tamamlandi()
            return

        self._gecen_ms += 100

        # İlerleme çubuğu
        if self._mevcut_sure_ms > 0:
            yuzde = min(100, int(self._gecen_ms / self._mevcut_sure_ms * 100))
            self._progress.setValue(yuzde)

        # Süre metni
        gecen_str = self._ms_to_str(self._gecen_ms)
        toplam_str = self._ms_to_str(self._mevcut_sure_ms)
        self._lbl_sure.setText(f"{gecen_str} / {toplam_str}")

    def _oynatma_tamamlandi(self):
        """Oynatma bittiğinde çağrılır."""
        self._oynuyor = False
        self._timer.stop()
        self._btn_oynat.setText("▶ Oynat")
        self._progress.setValue(100)

        toplam_str = self._ms_to_str(self._mevcut_sure_ms)
        self._lbl_sure.setText(f"{toplam_str} / {toplam_str}")
        self._lbl_durum.setText("Tamamlandı.")
        self._lbl_durum.setStyleSheet("font-size: 9px; color: #2196F3;")

        self.oynatma_bitti.emit()

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------

    @staticmethod
    def _sure_hesapla(dosya_yolu: str) -> int:
        """Ses dosyasının süresini ms olarak hesaplar."""
        try:
            import soundfile as sf
            bilgi = sf.info(dosya_yolu)
            return int(bilgi.duration * 1000)
        except Exception:
            return 0

    @staticmethod
    def _ms_to_str(ms: int) -> str:
        """Milisaniyeyi 'D:SS' formatına çevirir."""
        if ms < 0:
            ms = 0
        toplam_sn = ms // 1000
        dakika = toplam_sn // 60
        saniye = toplam_sn % 60
        return f"{dakika}:{saniye:02d}"

    @property
    def oynuyor(self) -> bool:
        return self._oynuyor

    @property
    def mevcut_dosya(self) -> str:
        return self._mevcut_dosya
