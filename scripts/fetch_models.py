"""Téléchargement explicite d'un modèle Whisper (seule étape réseau de Dictera).

Usage : .venv\\Scripts\\python scripts\\fetch_models.py [large-v3-turbo|large-v3]
Destination : %LOCALAPPDATA%\\Dictera\\models. Ensuite, Dictera fonctionne hors ligne.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from faster_whisper.utils import download_model  # noqa: E402

from dictera.transcriber import DEFAULT_MODEL, MODELS, models_dir  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    if name not in MODELS:
        print(f"Modèle inconnu : {name}. Choix : {', '.join(MODELS)}")
        return 2
    print(f"Téléchargement de {name} vers {models_dir()} …")
    path = download_model(name, cache_dir=str(models_dir()))
    size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    print(f"OK : {path} ({size / 1e9:.2f} Go)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
