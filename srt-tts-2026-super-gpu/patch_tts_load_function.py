# -*- coding: utf-8 -*-
"""
DubSync Pro - TTS load_with_torchcodec Patch

Sorun: coqui-tts 0.27.5 dahili load_with_torchcodec kullanir.
       torchcodec kuruluysa Windows nightly'de WinError 87,
       kurulu degilse "required" hatasi verir.

Cozum: TTS paketinin kaynak kodundaki load_with_torchcodec
       fonksiyonunu soundfile backend ile degistir.

Kullanim:
    cd C:\\kodlamalar\\python\\srt-tts-2026-super-gpu
    pip install torchcodec
    python patch_tts_load_function.py
    python main.py --debug
"""

import os
import sys
import glob
import shutil
from datetime import datetime


def bul_ve_patch(site_packages):
    """TTS paketinde load_with_torchcodec fonksiyonunu bulur ve patch eder."""
    
    patched = 0
    
    # TTS paketindeki tum Python dosyalarini tara
    tts_dir = os.path.join(site_packages, "TTS")
    if not os.path.isdir(tts_dir):
        print(f"  HATA: TTS paketi bulunamadi: {tts_dir}")
        return 0
    
    print(f"  TTS dizini: {tts_dir}")
    print(f"  load_with_torchcodec araniyor...\n")
    
    for root, dirs, files in os.walk(tts_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
            
            if "load_with_torchcodec" not in content:
                continue
            
            rel = os.path.relpath(fpath, site_packages)
            
            # def load_with_torchcodec iceren dosyayi bul
            if "def load_with_torchcodec" in content:
                print(f"  BULUNDU (tanim): {rel}")
                
                # Zaten patch edilmis mi?
                if "# DUBSYNC_PATCHED" in content:
                    print(f"    -> Zaten patch edilmis.\n")
                    patched += 1
                    continue
                
                # Yedek al
                yedek = fpath + f".bak_{datetime.now().strftime('%H%M%S')}"
                shutil.copy2(fpath, yedek)
                
                # Fonksiyon tanimini bul ve degistir
                lines = content.split("\n")
                new_lines = []
                skip_until_next_def = False
                indent_level = 0
                func_found = False
                
                i = 0
                while i < len(lines):
                    line = lines[i]
                    
                    if "def load_with_torchcodec" in line and not skip_until_next_def:
                        func_found = True
                        # Indent seviyesini bul
                        indent_level = len(line) - len(line.lstrip())
                        indent = " " * indent_level
                        
                        # Yeni fonksiyonu yaz
                        new_lines.append(f"{indent}def load_with_torchcodec(file_path, sample_rate=None):  # DUBSYNC_PATCHED")
                        new_lines.append(f'{indent}    """Patched: soundfile backend (torchcodec Windows fix)."""')
                        new_lines.append(f"{indent}    import soundfile as sf")
                        new_lines.append(f"{indent}    import numpy as np")
                        new_lines.append(f"{indent}    import torch")
                        new_lines.append(f"{indent}    data, sr = sf.read(file_path, dtype='float32')")
                        new_lines.append(f"{indent}    if data.ndim > 1:")
                        new_lines.append(f"{indent}        data = np.mean(data, axis=1)")
                        new_lines.append(f"{indent}    wav = torch.from_numpy(data).unsqueeze(0)")
                        new_lines.append(f"{indent}    if sample_rate is not None and sample_rate != sr:")
                        new_lines.append(f"{indent}        try:")
                        new_lines.append(f"{indent}            import torchaudio")
                        new_lines.append(f"{indent}            wav = torchaudio.functional.resample(wav, sr, sample_rate)")
                        new_lines.append(f"{indent}            sr = sample_rate")
                        new_lines.append(f"{indent}        except Exception:")
                        new_lines.append(f"{indent}            pass")
                        new_lines.append(f"{indent}    return wav, sr")
                        
                        # Eski fonksiyon govdesini atla
                        skip_until_next_def = True
                        i += 1
                        continue
                    
                    if skip_until_next_def:
                        # Bir sonraki ayni veya daha ust seviye tanim/satirda dur
                        stripped = line.strip()
                        if stripped == "":
                            # Bos satir — kontrol et sonraki satir ne
                            # Bos satirlari topla
                            blank_lines = [line]
                            j = i + 1
                            while j < len(lines) and lines[j].strip() == "":
                                blank_lines.append(lines[j])
                                j += 1
                            
                            if j < len(lines):
                                next_line = lines[j]
                                next_indent = len(next_line) - len(next_line.lstrip())
                                if next_indent <= indent_level and next_line.strip():
                                    # Fonksiyon bitti
                                    skip_until_next_def = False
                                    new_lines.extend(blank_lines)
                                    i = j
                                    continue
                            
                            # Henuz bitmedi, atla
                            i += 1
                            continue
                        
                        current_indent = len(line) - len(line.lstrip())
                        if current_indent <= indent_level and stripped and not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                            # Fonksiyon bitti, bu satiri dahil et
                            skip_until_next_def = False
                            new_lines.append("")  # Bos satir ekle
                            new_lines.append(line)
                            i += 1
                            continue
                        
                        # Hala fonksiyon icinde, atla
                        i += 1
                        continue
                    
                    new_lines.append(line)
                    i += 1
                
                if func_found:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write("\n".join(new_lines))
                    print(f"    -> PATCH UYGULANDI!")
                    print(f"    -> Yedek: {yedek}\n")
                    patched += 1
                
            else:
                # Sadece cagri var (import veya kullanim)
                print(f"  Referans: {rel}")
    
    return patched


def main():
    if not os.path.isdir("engines"):
        print("HATA: Proje kok dizininde calistirin!")
        sys.exit(1)
    
    print("=" * 60)
    print("DubSync Pro - TTS load_with_torchcodec Patch")
    print("=" * 60)
    print()
    
    # Site packages bul
    venv_sp = os.path.join("venv", "Lib", "site-packages")
    if not os.path.isdir(venv_sp):
        # Linux/Mac
        for sp in glob.glob("venv/lib/python*/site-packages"):
            venv_sp = sp
            break
    
    if not os.path.isdir(venv_sp):
        print(f"HATA: site-packages bulunamadi!")
        sys.exit(1)
    
    patched = bul_ve_patch(venv_sp)
    
    print("=" * 60)
    if patched > 0:
        print(f"OK: {patched} dosya patch edildi!")
        print()
        print("Test:")
        print("  python main.py --debug")
    else:
        print("UYARI: Hicbir dosya patch edilemedi.")
    print("=" * 60)


if __name__ == "__main__":
    main()
