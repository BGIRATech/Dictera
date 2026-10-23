"""Réglages persistants (JSON dans %APPDATA%\\Dictera)."""

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

# Touches proposées pour le push-to-talk : nom affiché -> code virtuel Windows.
HOTKEYS = {
    "RCTRL": ("Ctrl droit", 0xA3),
    "LCTRL": ("Ctrl gauche", 0xA2),
    "RALT": ("Alt droit", 0xA5),
    "RSHIFT": ("Maj droite", 0xA1),
    "RWIN": ("Windows droit", 0x5C),
    "CAPSLOCK": ("Verr. Maj", 0x14),
    "SCROLLLOCK": ("Arrêt défil.", 0x91),
    "PAUSE": ("Pause", 0x13),
    "INSERT": ("Inser", 0x2D),
    **{f"F{n}": (f"F{n}", 0x7C + n - 13) for n in range(13, 25)},
}
DEFAULT_HOTKEY = "RCTRL"


def config_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "Dictera"


def log_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Dictera" / "logs"


@dataclass
class Config:
    hotkey: str = DEFAULT_HOTKEY
    sounds_enabled: bool = True
    input_device: str | None = None  # None = périphérique d'entrée par défaut de Windows
    min_hold_ms: int = 200  # un maintien plus court est considéré comme accidentel
    max_record_s: int = 600  # garde-fou : la capture s'arrête seule au-delà
    whisper_model: str = "large-v3-turbo"  # ou "large-v3" (précision maximale)
    language: str = "fr"
    # Insertion (Phase 3)
    restore_clipboard: bool = True
    paste_delay_ms: int = 80  # entre l'écriture du presse-papiers et le Ctrl+V
    restore_delay_ms: int = 500  # entre le Ctrl+V et la restauration (l'appli lit à son rythme)
    paste_keys: str = "ctrl+v"  # ou "shift+insert" partout
    shift_insert_apps: list[str] = field(default_factory=lambda: ["mintty.exe", "putty.exe", "kitty.exe"])
    clipboard_no_history: bool = True  # texte dicté exclu de l'historique Win+V et du cloud
    # Reformulation (Phase 3)
    reformulation: str = "auto"  # auto | ollama | rules | off
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_s: float = 8.0
    # LLM local compatible OpenAI (LM Studio) : remplace Ollama s'il est activé
    llm_enabled: bool = True
    llm_url: str = "http://localhost:1234/v1/chat/completions"
    llm_model: str = "mistralai/mistral-nemo-instruct-2407"
    llm_timeout_s: float = 3.0  # au-delà : repli silencieux sur les règles
    llm_temperature: float = 0.2
    # Statistiques (Phase 4)
    typing_wpm: int = 40  # vitesse de frappe au clavier, pour le « temps gagné »
    # Interface (Phase 5)
    first_name: str = ""  # « Salut <prénom> » ; vide = nom d'affichage du compte Windows

    @property
    def hotkey_vk(self) -> int:
        return HOTKEYS[self.hotkey][1]

    @property
    def hotkey_label(self) -> str:
        return HOTKEYS[self.hotkey][0]

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_dir() / "config.json"
        cfg = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cfg
        except (OSError, ValueError) as e:
            log.warning("Config illisible (%s), valeurs par défaut utilisées", e)
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, value)
        if cfg.hotkey not in HOTKEYS:
            log.warning("Touche inconnue %r, retour à %s", cfg.hotkey, DEFAULT_HOTKEY)
            cfg.hotkey = DEFAULT_HOTKEY
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
