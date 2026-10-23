"""Ce que les pages peuvent lire et déclencher, sans dépendre de l'application entière."""

import ctypes
import getpass
import os
import winreg
from dataclasses import dataclass, field
from typing import Callable

from ..config import Config
from ..storage import Database
from ..vocabulary import Vocabulary


@dataclass
class EngineInfo:
    model: str = ""  # modèle Whisper chargé ("" tant qu'il charge)
    device: str = ""  # ex. "CUDA · RTX 4070 Ti"
    error: str = ""
    reformulation: str = ""  # état lisible du moteur de reformulation


@dataclass
class UiContext:
    db: Database
    config: Config
    vocabulary: Vocabulary
    engine_info: Callable[[], EngineInfo] = EngineInfo
    # Appelé après modification d'un réglage (clé de Config) : l'appli l'applique à chaud.
    on_setting_changed: Callable[[str], None] = lambda _key: None
    # Appelé après modification du dictionnaire : l'appli recharge le vocabulaire.
    on_vocabulary_changed: Callable[[], None] = lambda: None
    listeners: list[Callable[[], None]] = field(default_factory=list)


def first_name(config: Config) -> str:
    """Prénom du bandeau : réglage explicite, sinon nom d'affichage Windows, sinon identifiant."""
    if getattr(config, "first_name", ""):
        return config.first_name
    try:
        size = ctypes.c_ulong(256)
        buf = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) and buf.value.strip():  # NameDisplay
            return buf.value.split()[0]
    except (OSError, AttributeError):
        pass
    name = os.environ.get("USERNAME") or getpass.getuser()
    return name[:1].upper() + name[1:]


def microphone_access() -> tuple[bool | None, str]:
    """État de l'autorisation Windows (Paramètres > Confidentialité > Microphone) pour les
    applications de bureau. (True, …) autorisé, (False, …) bloqué, (None, …) inconnu."""
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def read(path: str) -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                return winreg.QueryValueEx(k, "Value")[0]
        except OSError:
            return None

    global_value, desktop_value = read(base), read(base + r"\NonPackaged")
    if global_value == "Deny":
        return False, "Accès au micro désactivé dans Windows"
    if desktop_value == "Deny":
        return False, "Accès au micro refusé aux applications de bureau"
    if global_value is None and desktop_value is None:
        return None, "État de l'autorisation inconnu"
    return True, "Accès au micro autorisé"
