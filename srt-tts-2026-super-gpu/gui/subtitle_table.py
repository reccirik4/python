# -*- coding: utf-8 -*-
"""
DubSync Pro — Altyazı Tablosu (subtitle_table.py)

Tüm altyazı satırlarını tablo formatında gösterir.
Renk kodlu durum sütunu, sağ tık menüsü, çift tık önizleme,
karakter filtresi ve toplu karakter atama destekler.
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QColor, QBrush, QAction
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QComboBox,
    QLineEdit,
    QMenu,
    QAbstractItemView,
    QFrame,
)

from core.srt_parser import AltyaziDosyasi, AltyaziSatiri
from core.timing_analyzer import ZamanlamaSonucu, ZamanlamaDurum, TimingAnalyzer

logger = logging.getLogger("DubSync.SubtitleTable")

# Sütun indeksleri
KOL_SIRA = 0
KOL_BASLANGIC = 1
KOL_BITIS = 2
KOL_SURE = 3
KOL_KARAKTER = 4
KOL_METIN = 5
KOL_DURUM = 6
SUTUN_SAYISI = 7

SUTUN_BASLIKLARI = ["#", "Başlangıç", "Bitiş", "Süre", "Karakter", "Metin", "Durum"]


class SubtitleTable(QWidget):
    """
    Altyazı satırlarını tablo olarak gösteren widget.

    Özellikler:
    - Renk kodlu durum sütunu (yeşil/sarı/turuncu/kırmızı/mavi/gri)
    - Çift tık ile satır önizleme
    - Sağ tık menüsü (karakter ata, önizle, bilgi)
    - Karakter ve metin filtreleme
    - Toplu seçim ve karakter atama
    - Zamanlama sonuçları görselleştirme
    """

    # Sinyaller
    satir_cift_tiklandi = pyqtSignal(int)       # Çift tık: satır sıra no
    satir_sag_tiklandi = pyqtSignal(int)        # Sağ tık: satır sıra no
    karakter_atama_istendi = pyqtSignal(list, str)  # Seçili satırlar, karakter_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dosya: Optional[AltyaziDosyasi] = None
        self._zamanlama: dict[int, ZamanlamaSonucu] = {}
        self._tum_satirlar: list[AltyaziSatiri] = []

        self._olustur()

    def _olustur(self):
        """Widget yapısını oluşturur."""
        ana_layout = QVBoxLayout(self)
        ana_layout.setContentsMargins(0, 0, 0, 0)
        ana_layout.setSpacing(4)

        # --- Üst: Filtre çubuğu ---
        filtre_layout = QHBoxLayout()
        filtre_layout.setSpacing(6)

        lbl_filtre = QLabel("🔍")
        lbl_filtre.setFixedWidth(20)
        filtre_layout.addWidget(lbl_filtre)

        # Metin filtresi
        self._txt_filtre = QLineEdit()
        self._txt_filtre.setPlaceholderText("Metin ara...")
        self._txt_filtre.setMaximumHeight(28)
        self._txt_filtre.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self._txt_filtre.textChanged.connect(self._filtre_uygula)
        filtre_layout.addWidget(self._txt_filtre, stretch=1)

        # Karakter filtresi
        lbl_karakter = QLabel("Karakter:")
        lbl_karakter.setStyleSheet("font-size: 11px;")
        filtre_layout.addWidget(lbl_karakter)

        self._cmb_karakter_filtre = QComboBox()
        self._cmb_karakter_filtre.addItem("Tümü", "")
        self._cmb_karakter_filtre.setMinimumWidth(130)
        self._cmb_karakter_filtre.setMaximumHeight(28)
        self._cmb_karakter_filtre.setStyleSheet("font-size: 11px;")
        self._cmb_karakter_filtre.currentIndexChanged.connect(self._filtre_uygula)
        filtre_layout.addWidget(self._cmb_karakter_filtre)

        # Durum filtresi
        lbl_durum = QLabel("Durum:")
        lbl_durum.setStyleSheet("font-size: 11px;")
        filtre_layout.addWidget(lbl_durum)

        self._cmb_durum_filtre = QComboBox()
        self._cmb_durum_filtre.addItem("Tümü", "")
        self._cmb_durum_filtre.addItem("✅ Sığıyor", "sigiyor")
        self._cmb_durum_filtre.addItem("⚡ Hızlandır", "hizlandir")
        self._cmb_durum_filtre.addItem("❌ Taşma", "tasma")
        self._cmb_durum_filtre.setMinimumWidth(120)
        self._cmb_durum_filtre.setMaximumHeight(28)
        self._cmb_durum_filtre.setStyleSheet("font-size: 11px;")
        self._cmb_durum_filtre.currentIndexChanged.connect(self._filtre_uygula)
        filtre_layout.addWidget(self._cmb_durum_filtre)

        ana_layout.addLayout(filtre_layout)

        # --- Tablo ---
        self._tablo = QTableWidget()
        self._tablo.setColumnCount(SUTUN_SAYISI)
        self._tablo.setHorizontalHeaderLabels(SUTUN_BASLIKLARI)
        self._tablo.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tablo.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tablo.setAlternatingRowColors(True)
        self._tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tablo.setSortingEnabled(False)
        self._tablo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Sütun genişlikleri
        header = self._tablo.horizontalHeader()
        header.setSectionResizeMode(KOL_SIRA, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(KOL_BASLANGIC, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(KOL_BITIS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(KOL_SURE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(KOL_KARAKTER, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(KOL_METIN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(KOL_DURUM, QHeaderView.ResizeMode.Fixed)

        self._tablo.setColumnWidth(KOL_SIRA, 50)
        self._tablo.setColumnWidth(KOL_BASLANGIC, 100)
        self._tablo.setColumnWidth(KOL_BITIS, 100)
        self._tablo.setColumnWidth(KOL_SURE, 60)
        self._tablo.setColumnWidth(KOL_KARAKTER, 110)
        self._tablo.setColumnWidth(KOL_DURUM, 50)

        # Satır yüksekliği
        self._tablo.verticalHeader().setDefaultSectionSize(26)
        self._tablo.verticalHeader().setVisible(False)

        # Stil — Windows dark mode uyumluluğu için renkleri açıkça belirt
        self._tablo.setStyleSheet(
            "QTableWidget { font-size: 11px; gridline-color: #ddd; "
            "background-color: #ffffff; color: #222222; "
            "alternate-background-color: #f5f5f5; "
            "selection-background-color: #0078d4; selection-color: #ffffff; }"
            "QTableWidget::item { padding: 2px 6px; color: #222222; }"
            "QHeaderView::section { font-size: 11px; font-weight: bold; "
            "padding: 4px; background-color: #e8e8e8; color: #333333; "
            "border: 1px solid #ccc; }"
        )

        # Sinyaller
        self._tablo.doubleClicked.connect(self._cift_tik)
        self._tablo.customContextMenuRequested.connect(self._sag_tik_menu)

        ana_layout.addWidget(self._tablo, stretch=1)

        # --- Alt: Bilgi çubuğu ---
        self._lbl_bilgi = QLabel("Henüz altyazı yüklenmedi.")
        self._lbl_bilgi.setStyleSheet("font-size: 10px; color: #888; padding: 2px;")
        ana_layout.addWidget(self._lbl_bilgi)

    # --------------------------------------------------------
    # Veri Yükleme
    # --------------------------------------------------------

    def altyazi_yukle(self, dosya: AltyaziDosyasi):
        """
        Altyazı dosyasını tabloya yükler.

        Args:
            dosya: AltyaziDosyasi nesnesi.
        """
        self._dosya = dosya
        self._tum_satirlar = list(dosya.satirlar)
        self._zamanlama.clear()

        # Karakter filtresini güncelle
        self._cmb_karakter_filtre.blockSignals(True)
        self._cmb_karakter_filtre.clear()
        self._cmb_karakter_filtre.addItem("Tümü", "")
        for kid in dosya.konusmacilar:
            isim = dosya.konusmacilar[kid].get("isim", "")
            etiket = f"{kid}" if not isim else f"{kid} ({isim})"
            self._cmb_karakter_filtre.addItem(etiket, kid)
        self._cmb_karakter_filtre.blockSignals(False)

        # Tabloyu doldur
        self._tabloyu_doldur(self._tum_satirlar)

        self._bilgi_guncelle()
        logger.info("Tablo yüklendi: %d satır", dosya.satir_sayisi)

    def zamanlama_guncelle(self, zamanlama: dict[int, ZamanlamaSonucu]):
        """
        Zamanlama analiz sonuçlarını tabloya uygular.

        Args:
            zamanlama: {satir_sira: ZamanlamaSonucu} sözlüğü.
        """
        self._zamanlama = zamanlama

        for satir_idx in range(self._tablo.rowCount()):
            sira_item = self._tablo.item(satir_idx, KOL_SIRA)
            if sira_item is None:
                continue
            sira = int(sira_item.text())
            zs = zamanlama.get(sira)
            if zs:
                self._durum_hucresini_ayarla(satir_idx, zs)

        self._bilgi_guncelle()

    # --------------------------------------------------------
    # Tablo Doldurma
    # --------------------------------------------------------

    def _tabloyu_doldur(self, satirlar: list[AltyaziSatiri]):
        """Satırları tabloya ekler."""
        self._tablo.setUpdatesEnabled(False)
        self._tablo.setRowCount(0)
        self._tablo.setRowCount(len(satirlar))

        for idx, satir in enumerate(satirlar):
            # Sıra
            item_sira = QTableWidgetItem(str(satir.sira))
            item_sira.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_SIRA, item_sira)

            # Başlangıç
            item_bas = QTableWidgetItem(satir.baslangic_str)
            item_bas.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_BASLANGIC, item_bas)

            # Bitiş
            item_bit = QTableWidgetItem(satir.bitis_str)
            item_bit.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_BITIS, item_bit)

            # Süre
            sure_str = f"{satir.sure_ms / 1000:.1f}s"
            item_sure = QTableWidgetItem(sure_str)
            item_sure.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_SURE, item_sure)

            # Karakter
            karakter_str = satir.konusmaci_isim or satir.konusmaci_id or ""
            item_karakter = QTableWidgetItem(karakter_str)
            item_karakter.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_KARAKTER, item_karakter)

            # Metin
            item_metin = QTableWidgetItem(satir.temiz_metin)
            self._tablo.setItem(idx, KOL_METIN, item_metin)

            # Durum (zamanlama varsa doldurulur)
            item_durum = QTableWidgetItem("—")
            item_durum.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tablo.setItem(idx, KOL_DURUM, item_durum)

            # Zamanlama varsa uygula
            zs = self._zamanlama.get(satir.sira)
            if zs:
                self._durum_hucresini_ayarla(idx, zs)

        self._tablo.setUpdatesEnabled(True)

    def _durum_hucresini_ayarla(self, satir_idx: int, zs: ZamanlamaSonucu):
        """Durum sütunundaki hücreyi zamanlama sonucuna göre renklendirir."""
        ikon = TimingAnalyzer.durum_ikon(zs.durum)
        renk_hex = TimingAnalyzer.durum_renk(zs.durum)

        item = self._tablo.item(satir_idx, KOL_DURUM)
        if item is None:
            item = QTableWidgetItem()
            self._tablo.setItem(satir_idx, KOL_DURUM, item)

        item.setText(ikon)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(
            f"Durum: {zs.durum.value}\n"
            f"Hız oranı: {zs.hiz_orani:.2f}x\n"
            f"Ses: {zs.ses_ms}ms / Slot: {zs.slot_ms}ms\n"
            f"{zs.uyari}"
        )

        # Satır arka plan rengi (hafif)
        renk = QColor(renk_hex)
        renk.setAlpha(30)
        for kol in range(SUTUN_SAYISI):
            hucre = self._tablo.item(satir_idx, kol)
            if hucre:
                hucre.setBackground(QBrush(renk))

    # --------------------------------------------------------
    # Filtreleme
    # --------------------------------------------------------

    def _filtre_uygula(self):
        """Metin, karakter ve durum filtrelerini uygular."""
        metin_filtre = self._txt_filtre.text().strip().lower()
        karakter_filtre = self._cmb_karakter_filtre.currentData() or ""
        durum_filtre = self._cmb_durum_filtre.currentData() or ""

        filtreli = []
        for satir in self._tum_satirlar:
            # Metin filtresi
            if metin_filtre and metin_filtre not in satir.temiz_metin.lower():
                continue

            # Karakter filtresi
            if karakter_filtre and satir.konusmaci_id != karakter_filtre:
                continue

            # Durum filtresi
            if durum_filtre:
                zs = self._zamanlama.get(satir.sira)
                if zs is None:
                    continue
                if durum_filtre == "hizlandir":
                    if zs.durum not in (ZamanlamaDurum.HAFIF_HIZLANDIR, ZamanlamaDurum.ORTA_HIZLANDIR):
                        continue
                elif durum_filtre == "sigiyor" and zs.durum != ZamanlamaDurum.SIGIYOR:
                    continue
                elif durum_filtre == "tasma" and zs.durum != ZamanlamaDurum.TASMA:
                    continue

            filtreli.append(satir)

        self._tabloyu_doldur(filtreli)
        self._lbl_bilgi.setText(
            f"Gösterilen: {len(filtreli)} / {len(self._tum_satirlar)} satır"
        )

    # --------------------------------------------------------
    # Sağ Tık Menü
    # --------------------------------------------------------

    def _sag_tik_menu(self, pozisyon):
        """Sağ tık bağlam menüsü."""
        secili = self._secili_sira_numaralari()
        if not secili:
            return

        menu = QMenu(self)

        # Önizle
        act_onizle = QAction(f"▶ Önizle (Satır {secili[0]})", self)
        act_onizle.triggered.connect(lambda: self.satir_cift_tiklandi.emit(secili[0]))
        menu.addAction(act_onizle)

        menu.addSeparator()

        # Karakter atama alt menüsü
        if self._dosya and self._dosya.konusmacilar:
            karakter_menu = menu.addMenu("Karakter Ata")
            for kid in self._dosya.konusmacilar:
                act = QAction(kid, self)
                act.triggered.connect(
                    lambda checked, k=kid: self.karakter_atama_istendi.emit(secili, k)
                )
                karakter_menu.addAction(act)

        menu.addSeparator()

        # Bilgi
        if len(secili) == 1:
            satir = self._satir_bul(secili[0])
            if satir:
                zs = self._zamanlama.get(secili[0])
                bilgi_str = (
                    f"Sıra: {satir.sira}\n"
                    f"Zaman: {satir.baslangic_str} → {satir.bitis_str}\n"
                    f"Süre: {satir.sure_ms}ms\n"
                    f"Karakter: {satir.konusmaci_id}\n"
                    f"Metin: {satir.temiz_metin[:60]}..."
                )
                if zs:
                    bilgi_str += (
                        f"\nDurum: {zs.durum.value}"
                        f"\nHız oranı: {zs.hiz_orani:.2f}x"
                    )
                act_bilgi = QAction("ℹ Bilgi", self)
                act_bilgi.setToolTip(bilgi_str)
                act_bilgi.setEnabled(False)  # Sadece gösterim
                menu.addAction(act_bilgi)

        # Seçim bilgisi
        act_secim = QAction(f"Seçili: {len(secili)} satır", self)
        act_secim.setEnabled(False)
        menu.addAction(act_secim)

        menu.exec(self._tablo.viewport().mapToGlobal(pozisyon))

    # --------------------------------------------------------
    # Çift Tık
    # --------------------------------------------------------

    def _cift_tik(self, index: QModelIndex):
        """Çift tıklanan satırın sıra numarasını emit eder."""
        sira_item = self._tablo.item(index.row(), KOL_SIRA)
        if sira_item:
            sira = int(sira_item.text())
            self.satir_cift_tiklandi.emit(sira)

    # --------------------------------------------------------
    # Seçim Yardımcıları
    # --------------------------------------------------------

    def _secili_sira_numaralari(self) -> list[int]:
        """Seçili satırların sıra numaralarını döndürür."""
        secili = []
        for idx in self._tablo.selectionModel().selectedRows():
            sira_item = self._tablo.item(idx.row(), KOL_SIRA)
            if sira_item:
                secili.append(int(sira_item.text()))
        return secili

    def _satir_bul(self, sira: int) -> Optional[AltyaziSatiri]:
        """Sıra numarasına göre AltyaziSatiri bulur."""
        for satir in self._tum_satirlar:
            if satir.sira == sira:
                return satir
        return None

    def satira_git(self, sira: int):
        """Belirtilen sıra numarasına sahip satıra scroll eder ve seçer."""
        for idx in range(self._tablo.rowCount()):
            item = self._tablo.item(idx, KOL_SIRA)
            if item and int(item.text()) == sira:
                self._tablo.selectRow(idx)
                self._tablo.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    # --------------------------------------------------------
    # Bilgi
    # --------------------------------------------------------

    def _bilgi_guncelle(self):
        """Alt bilgi etiketini günceller."""
        if not self._dosya:
            self._lbl_bilgi.setText("Henüz altyazı yüklenmedi.")
            return

        toplam = len(self._tum_satirlar)
        gosterilen = self._tablo.rowCount()

        bilgi_parcalari = [f"Toplam: {toplam} satır"]

        if self._zamanlama:
            sayaclar = {}
            for zs in self._zamanlama.values():
                ad = zs.durum.value
                sayaclar[ad] = sayaclar.get(ad, 0) + 1

            for ad, sayi in sayaclar.items():
                bilgi_parcalari.append(f"{ad}: {sayi}")

        if gosterilen != toplam:
            bilgi_parcalari.insert(0, f"Gösterilen: {gosterilen}")

        self._lbl_bilgi.setText("  |  ".join(bilgi_parcalari))

    @property
    def satir_sayisi(self) -> int:
        """Tablodaki toplam satır sayısı."""
        return len(self._tum_satirlar)
