# DubSync Pro v1.0 — Kurulum ve Kullanım Kılavuzu
### GPU Versiyonu (RTX 5050 Blackwell)

---

## Ne İşe Yarar?

DubSync Pro, video altyazılarını (SRT dosyası) otomatik olarak seslendirir.

- Video + SRT dosyası verirsin → Türkçe (veya başka dilde) sesli video çıkar
- İstersen kendi sesini klonlayabilir (6 saniyelik ses örneğiyle)
- GPU ile ~5-8x hızlı çalışır

---

## Gereksinimler

- Windows 10/11 (64-bit)
- Python 3.12
- NVIDIA GPU (RTX 5050 veya CUDA destekli herhangi bir kart)
- FFmpeg (PATH'te kurulu olmalı)
- İnternet bağlantısı (ilk kurulum ve Edge TTS için)

---

## Kurulum (Adım Adım)

### 1. Proje klasörünü aç

```
cd C:\kodlamalar\python\srt-tts-2026-super-gpu
```

### 2. Otomatik kurulum (önerilen)

```
setup_gpu_venv.bat
```

Bu script her şeyi sırayla kurar:
- Sanal ortam oluşturur
- Paketleri yükler
- PyTorch nightly GPU versiyonunu kurar
- CUDA testini yapar
- torchaudio patch'ini uygular

Bitti. 5. adıma atla.

### 3. Manuel kurulum (isterseniz)

```
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements_gpu.txt
pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
python patch_torchaudio_torchcodec.py
```

### 4. Kurulumu doğrula

```
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Çıktıda `True` yazmalı.

### 5. Çalıştır

```
python main.py
```

Debug modunda çalıştırmak için:

```
python main.py --debug
```

---

## Kullanım

### Temel İş Akışı

1. **Video yükle** → Sol üstteki "Video Seç" butonuyla .mp4 dosyanı seç
2. **SRT yükle** → "SRT Seç" butonuyla altyazı dosyanı seç
3. **Karakter ayarla** → Her konuşmacıya ses motoru ve ses tonu ata
4. **Seslendir** → "Seslendir" butonuna bas, bekle
5. **Çıktı** → Video klasöründe `dubsync_output/` altında oluşur

### Ses Motorları

| Motor | Özellik | Maliyet |
|-------|---------|---------|
| Edge TTS | Hızlı, 322 ses, internet gerekli | Ücretsiz |
| XTTS-v2 | Ses klonlama, GPU ile hızlı, lokal | Ücretsiz |
| OpenAI TTS | Yüksek kalite, API key gerekli | Ücretli |
| ElevenLabs | En iyi kalite, API key gerekli | Ücretli |

### Ses Klonlama (XTTS-v2)

1. Karakterin yanındaki "Klon" butonuna tıkla
2. 6+ saniyelik temiz ses dosyası seç (.wav)
3. Motor olarak "XTTS-v2" seç
4. Seslendir — kendi sesinle konuşan video çıkar

---

## EXE Oluşturma (Opsiyonel)

Başkalarına dağıtmak istersen:

```
build_exe.bat
```

Çıktı: `dist\DubSync_Pro.exe` (~2-3 GB, GPU dahil)

---

## Dosya Yapısı

```
srt-tts-2026-super-gpu/
├── main.py                          ← Ana giriş noktası
├── requirements_gpu.txt             ← GPU bağımlılıkları
├── setup_gpu_venv.bat               ← Otomatik kurulum
├── build_exe.bat                    ← EXE oluşturucu
├── dubsync_pro.spec                 ← PyInstaller ayarları
├── patch_torchaudio_torchcodec.py   ← Windows GPU fix (zorunlu)
├── dubsync_pro_settings.json        ← Ayarlar (otomatik oluşur)
├── core/                            ← İş mantığı
├── engines/                         ← TTS motorları
└── gui/                             ← Arayüz
```

---

## Sorun Giderme

**"CUDA mevcut değil" diyorsa:**
```
pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
```

**"torchcodec" veya "WinError 87" hatası:**
```
python patch_torchaudio_torchcodec.py
```

**"coqui-tts yüklü değil" diyorsa:**
```
pip install coqui-tts==0.27.5
```

**XTTS ilk çalıştırmada yavaş:**
Normal. Model indiriliyor (~1.8 GB). Bir kere inince hızlanır.

**FFmpeg bulunamadı:**
https://ffmpeg.org/download.html adresinden indir, PATH'e ekle.

---

## Notlar

- İlk XTTS çalıştırması modeli indirir (~1.8 GB), sabırlı ol
- GPU belleği dolduğunda CPU'ya otomatik düşer
- Settings dosyası otomatik oluşur, elle düzenlemeye gerek yok
- Edge TTS internet gerektirir, XTTS-v2 tamamen lokal çalışır
