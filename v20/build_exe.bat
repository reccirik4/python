@echo off
chcp 65001 >nul
echo ══════════════════════════════════════════════════════════
echo   DubSync Pro — EXE Oluşturucu
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

echo [1/3] PyInstaller kontrol ediliyor...
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

echo [2/3] EXE oluşturuluyor (bu birkaç dakika sürebilir)...
echo       Torch dahil — boyut ~1-2GB olacak.
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
    echo   - Eksik modül: pip install -r requirements.txt
    echo   - Disk alanı: En az 3GB boş alan gerekli
    echo ══════════════════════════════════════════════════════════
    pause
    exit /b 1
)

echo.
echo [3/3] Settings dosyası kopyalanıyor...

REM ── Settings dosyasını EXE yanına kopyala ──
if exist "dubsync_pro_settings.json" (
    copy /Y "dubsync_pro_settings.json" "dist\dubsync_pro_settings.json" >nul
    echo       dubsync_pro_settings.json → dist\ kopyalandı.
) else (
    echo       [!] Settings dosyası bulunamadı — ilk çalıştırmada otomatik oluşturulur.
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
echo ══════════════════════════════════════════════════════════
pause
