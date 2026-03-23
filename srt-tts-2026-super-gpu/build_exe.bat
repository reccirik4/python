@echo off
chcp 65001 >nul
echo ══════════════════════════════════════════════════════════
echo   DubSync Pro v1.0 — GPU EXE Oluşturucu
echo   RTX 5050 Blackwell / PyTorch nightly cu128
echo ══════════════════════════════════════════════════════════
echo.

REM ── Venv aktif mi kontrol et ──
if "%VIRTUAL_ENV%"=="" (
    echo [!] Sanal ortam aktif degil.
    echo     Önce: venv\Scripts\activate
    echo.
    if exist "venv\Scripts\activate.bat" (
        echo     Otomatik aktif ediliyor...
        call venv\Scripts\activate.bat
    ) else (
        echo [HATA] venv klasörü bulunamadı!
        echo        Önce: py -3.12 -m venv venv
        pause
        exit /b 1
    )
)

echo [1/5] PyInstaller kontrol ediliyor...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo       PyInstaller yüklü degil. Kuruluyor...
    pip install pyinstaller
    if errorlevel 1 (
        echo [HATA] PyInstaller kurulamadı!
        pause
        exit /b 1
    )
)
echo       PyInstaller OK.
echo.

echo [2/5] GPU ortamı kontrol ediliyor...
python -c "import torch; assert torch.cuda.is_available(); print(f'       CUDA OK: {torch.cuda.get_device_name(0)}')" 2>nul
if errorlevel 1 (
    echo       [UYARI] CUDA kullanılamıyor! EXE CPU modunda çalışacak.
    echo       GPU için: pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
) else (
    echo.
)

echo [3/5] torchaudio torchcodec patch kontrol ediliyor...
python -c "import torchaudio._torchcodec as tc; import inspect; s=inspect.getsource(tc.load_with_torchcodec); assert 'soundfile' in s; print('       torchaudio patch OK.')" 2>nul
if errorlevel 1 (
    echo       [UYARI] torchaudio torchcodec patch uygulanmamış!
    echo       Önce: python patch_torchaudio_torchcodec.py
    echo.
    choice /C EH /M "       Devam etmek istiyor musunuz? (E/H)"
    if errorlevel 2 (
        echo       İptal edildi.
        pause
        exit /b 1
    )
)
echo.

echo [4/5] EXE oluşturuluyor (bu birkaç dakika sürebilir)...
echo       GPU Torch dahil — boyut ~2-3GB olacak.
echo.

pyinstaller dubsync_pro.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════════════════
    echo [HATA] EXE oluşturulamadı!
    echo        Hata detayları için yukarıdaki çıktıya bakın.
    echo.
    echo   Sık karşılaşılan sorunlar:
    echo   - Antivirüs engeli: Geçici olarak devre dışı bırakın
    echo   - Eksik modül: pip install -r requirements_gpu.txt
    echo   - Disk alanı: En az 5GB boş alan gerekli (GPU)
    echo   - torchaudio patch: python patch_torchaudio_torchcodec.py
    echo ══════════════════════════════════════════════════════════
    pause
    exit /b 1
)

echo.
echo [5/5] Dosyalar kopyalanıyor...

REM ── Settings dosyasını EXE yanına kopyala ──
if exist "dubsync_pro_settings.json" (
    copy /Y "dubsync_pro_settings.json" "dist\dubsync_pro_settings.json" >nul
    echo       dubsync_pro_settings.json → dist\ kopyalandı.
) else (
    echo       [!] Settings dosyası bulunamadı — ilk çalıştırmada otomatik oluşturulur.
)

REM ── Patch scriptini de kopyala (yeniden kurulumda lazım olur) ──
if exist "patch_torchaudio_torchcodec.py" (
    copy /Y "patch_torchaudio_torchcodec.py" "dist\patch_torchaudio_torchcodec.py" >nul
    echo       patch_torchaudio_torchcodec.py → dist\ kopyalandı.
)

echo.
echo ══════════════════════════════════════════════════════════
echo   BAŞARILI!
echo.
echo   EXE konumu:  dist\DubSync_Pro.exe
echo   Boyut:       
for %%F in (dist\DubSync_Pro.exe) do echo                %%~zF bytes
echo.
echo   Dağıtım için şunları birlikte verin:
echo     1. dist\DubSync_Pro.exe
echo     2. dist\dubsync_pro_settings.json
echo.
echo   NOT: FFmpeg sistemde yüklü olmalıdır (PATH'te).
echo        https://ffmpeg.org/download.html
echo.
echo   GPU: RTX 5050 / Blackwell — torch nightly cu128
echo        XTTS-v2 GPU'da ~5-8x hızlı çalışacak.
echo ══════════════════════════════════════════════════════════
pause
