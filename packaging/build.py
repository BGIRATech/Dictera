"""Construit dist\\Dictera\\Dictera.exe (Windows x64).

  1. icône (.ico multi-taille, dessinée depuis le logo) et informations de version ;
  2. PyInstaller (packaging\\dictera.spec) ;
  3. copie du modèle Whisper dans dist\\Dictera\\models\\<nom> : l'application est
     utilisable hors ligne dès l'installation (option --no-model pour l'omettre) ;
  4. résumé : taille par composant.

Usage : .venv\\Scripts\\python packaging\\build.py [--no-model] [--model large-v3-turbo]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dictera import __version__  # noqa: E402
from dictera.transcriber import DEFAULT_MODEL, MODELS, models_dir  # noqa: E402

BUILD = ROOT / "build" / "packaging"
DIST = ROOT / "dist" / "Dictera"
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json")
_REPOS = {"large-v3-turbo": "mobiuslabsgmbh--faster-whisper-large-v3-turbo",
          "large-v3": "Systran--faster-whisper-large-v3"}


def make_icon(path: Path) -> None:
    from PySide6.QtGui import QGuiApplication, QImage, QPainter

    from dictera.ui.theme import logo_pixmap

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 — requis pour dessiner
    # Le plugin ICO de Qt n'écrit qu'une image : on assemble un .ico multi-taille à la main.
    images = []
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        p.drawPixmap(0, 0, logo_pixmap(size))
        p.end()
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        images.append((size, bytes(data)))
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(images).to_bytes(2, "little")
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(png).to_bytes(4, "little") + (offset + len(blobs)).to_bytes(4, "little")
        blobs += png
    path.write_bytes(header + entries + blobs)


def make_version_file(path: Path) -> None:
    parts = [int(x) for x in __version__.split(".")] + [0] * 4
    v = tuple(parts[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'Dictera'),
      StringStruct('FileDescription', 'Dictera'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'Dictera'),
      StringStruct('OriginalFilename', 'Dictera.exe'),
      StringStruct('ProductName', 'Dictera — dictée vocale 100 % locale'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
""", encoding="utf-8")


def find_model(name: str) -> Path:
    snapshots = models_dir() / f"models--{_REPOS[name]}" / "snapshots"
    for snap in sorted(snapshots.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if (snap / "model.bin").exists():
            return snap
    raise SystemExit(f"Modèle {name} absent de {models_dir()}. Téléchargez-le d'abord :\n"
                     f"  .venv\\Scripts\\python scripts\\fetch_models.py {name}\n"
                     "ou construisez sans modèle : packaging\\build.py --no-model")


def copy_model(name: str) -> Path:
    src = find_model(name)
    dst = DIST / "models" / name
    dst.mkdir(parents=True, exist_ok=True)
    for f in MODEL_FILES:
        if (src / f).exists():
            shutil.copy2((src / f).resolve(), dst / f)  # resolve : le cache peut contenir des liens
    return dst


def size_of(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-model", action="store_true", help="ne pas inclure de modèle Whisper")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=MODELS)
    args = parser.parse_args()
    if not args.no_model:
        find_model(args.model)  # échouer tout de suite plutôt qu'après 5 minutes de build

    BUILD.mkdir(parents=True, exist_ok=True)
    make_icon(BUILD / "dictera.ico")
    make_version_file(BUILD / "version.txt")
    print(f"Icône et version {__version__} : {BUILD}")

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(ROOT / "dist"), "--workpath", str(BUILD / "work"),
                    str(ROOT / "packaging" / "dictera.spec")], check=True, cwd=ROOT)

    if not args.no_model:
        print(f"Modèle copié : {copy_model(args.model)}")

    internal = DIST / "_internal"
    parts = {
        "DLL CUDA (cuBLAS, cuDNN)": size_of(internal / "nvidia"),
        "CTranslate2": size_of(internal / "ctranslate2"),
        "Qt (PySide6)": size_of(internal / "PySide6"),
        "modèle Whisper": size_of(DIST / "models"),
    }
    total = size_of(DIST)
    parts["reste (Python, numpy, PyAV…)"] = total - sum(parts.values())
    print(f"\n{DIST / 'Dictera.exe'}")
    for label, n in parts.items():
        print(f"  {label:32s} {n / 1e6:8.0f} Mo")
    print(f"  {'TOTAL':32s} {total / 1e6:8.0f} Mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
