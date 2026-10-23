# PyInstaller — Dictera, Windows x64, dossier unique (onedir).
# Un seul fichier (onefile) décompresserait ≈1,5 Go de DLL CUDA à chaque lancement :
# le dossier démarre instantanément. Lancer via packaging\build.py (icône, version, modèle).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
SITE = Path(sys.prefix) / "Lib" / "site-packages"
BUILD = ROOT / "build" / "packaging"

# DLL CUDA conservées à leur place relative (nvidia/<paquet>/bin) : gpu.register_cuda_dlls
# les y cherche sous _MEIPASS. cuDNN complet : les vraies dictées chargent ses sous-bibliothèques.
cuda = [(str(p), f"nvidia/{p.parent.parent.name}/bin") for name in ("cublas", "cudnn")
        for p in (SITE / "nvidia" / name / "bin").glob("*.dll") if p.name != "nvblas64_12.dll"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=collect_dynamic_libs("ctranslate2") + cuda,
    datas=collect_data_files("faster_whisper", includes=["assets/*"]),
    hiddenimports=["PySide6.QtNetwork"],
    excludes=[
        "onnxruntime",  # détection de parole (VAD) : non utilisée par Dictera
        "tkinter", "PySide6.QtTest",  # scripts de test uniquement
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtDBus",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dictera",
    console=False,  # appli de la zone de notification : pas de fenêtre de console
    icon=str(BUILD / "dictera.ico"),
    version=str(BUILD / "version.txt"),
    upx=False,  # UPX corrompt souvent les DLL CUDA et alerte les antivirus
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Dictera")
