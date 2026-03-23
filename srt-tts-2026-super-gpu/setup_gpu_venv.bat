@echo off
chcp 65001 >nul
echo ══════════════════════════════════════════════════════════
echo   DubSync Pro v1.0 — GPU Ortam Kurulumu
echo   RTX 5050 Blackwell / PyTorch nightly cu128
echo ══════════════════════════════════════════════════════════
echo.
echo   Bu script sıfırdan GPU venv kurar.
echo   Mevcut venv varsa SILINIR!
echo.
choice /C EH /M "Devam etmek istiyor musunuz? (E/H)"
if errorlevel 2 (
    echo İptal edildi.
    pause
    exit /b 0
)
echo.

REM ── 1. Mevcut venv sil ──
echo [1/6] Venv hazırlanıyor...
if exist "venv" (
    echo       Mevcut venv siliniyor...
    rmdir /S /Q venv
)
py -3.12 -m venv venv
if errorlevel 1 (
    echo [HATA] Python 3.12 bulunamadı!
    echo        py -3.12 --version ile kontrol edin.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
echo       venv oluşturuldu ve aktif.
echo.

REM ── 2. Temel paketler (torch hariç) ──
echo [2/6] Temel paketler kuruluyor...
pip install -r requirements_gpu.txt 2>nul
if errorlevel 1 (
    echo [UYARI] Bazı paketler kurulamadı — torch ayrı kurulacak.
)
echo       Temel paketler OK.
echo.

REM ── 3. PyTorch nightly cu128 ──
echo [3/6] PyTorch nightly cu128 kuruluyor (bu biraz sürebilir)...
pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
if errorlevel 1 (
    echo [HATA] PyTorch nightly kurulamadı!
    echo        İnternet bağlantınızı kontrol edin.
    pause
    exit /b 1
)
echo       PyTorch nightly cu128 OK.
echo.

REM ── 4. CUDA testi ──
echo [4/6] CUDA testi...
python -c "import torch; assert torch.cuda.is_available(), 'CUDA yok!'; print(f'       GPU: {torch.cuda.get_device_name(0)}'); t=torch.zeros(1,device='cuda'); print('       CUDA tensor testi OK.')"
if errorlevel 1 (
    echo [UYARI] CUDA çalışmıyor! CPU modunda devam edilecek.
)
echo.

REM ── 5. torchaudio torchcodec patch ──
echo [5/6] torchaudio torchcodec patch uygulanıyor...
if exist "patch_torchaudio_torchcodec.py" (
    python patch_torchaudio_torchcodec.py
) else (
    echo       [UYARI] patch_torchaudio_torchcodec.py bulunamadı!
    echo       Bu dosyayı proje kök dizinine koyun ve tekrar çalıştırın.
)
echo.

REM ── 6. Son kontrol ──
echo [6/6] Son kontrol...
python -c "from TTS.api import TTS; print('       coqui-tts OK')" 2>nul
if errorlevel 1 (
    echo       [UYARI] coqui-tts import hatası!
)
python -c "import torch; print(f'       torch {torch.__version__} CUDA={torch.cuda.is_available()}')"
echo.

echo ══════════════════════════════════════════════════════════
echo   KURULUM TAMAMLANDI!
echo.
echo   Test:     python main.py --debug
echo   EXE:      build_exe.bat
echo.
echo   Çalışan paketler listesi:
echo     pip freeze ^> requirements_gpu_calisiyor.txt
echo ══════════════════════════════════════════════════════════
pause
