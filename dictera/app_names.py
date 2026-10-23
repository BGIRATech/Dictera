"""Nom lisible d'une appli à partir de son exécutable (pastille de l'historique).

Ordre : table des applis courantes, puis la description de l'exécutable
(FileDescription des ressources de version), puis le nom du fichier.

Dans un navigateur, toutes les pages sont le même exécutable (chrome.exe) : le site
est reconnu au titre de la fenêtre, qui contient celui de l'onglet actif (« … - Gmail
- Google Chrome »). Seul le nom du site, pris dans une liste connue, est conservé : le
titre lui-même (sujet de mail, nom de document) n'est jamais stocké.
"""

import ctypes
import functools
import re
from ctypes import wintypes
from pathlib import PureWindowsPath

_BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
# Comparé, sans casse, à chaque segment du titre séparé par « - », « — », « – », « | » ou « · ».
_SITES = {name.lower(): name for name in (
    "Gmail", "Outlook", "Google Agenda", "Google Calendar", "Google Docs", "Google Sheets", "Google Slides",
    "Google Drive", "YouTube", "WhatsApp", "Messenger", "LinkedIn", "Facebook", "Instagram", "Reddit", "GitHub",
    "ChatGPT", "Claude", "Gemini", "Notion", "Slack", "Discord", "Trello", "Canva", "Figma", "Wikipédia",
)}
_TITLE_SEP = re.compile(r"\s+[-–—|·]\s+")

_KNOWN = {
    "notepad.exe": "Bloc-notes",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "olk.exe": "Outlook",
    "onenote.exe": "OneNote",
    "ms-teams.exe": "Teams",
    "teams.exe": "Teams",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "whatsapp.exe": "WhatsApp",
    "telegram.exe": "Telegram",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "windowsterminal.exe": "Terminal",
    "wt.exe": "Terminal",
    "cmd.exe": "Invite de commandes",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "explorer.exe": "Explorateur",
    "claude.exe": "Claude",
    "chatgpt.exe": "ChatGPT",
}

_version = ctypes.WinDLL("version", use_last_error=True)
_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID),
                                    ctypes.POINTER(wintypes.UINT)]
_version.VerQueryValueW.restype = wintypes.BOOL


def _file_description(path: str) -> str:
    size = _version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, buf):
        return ""
    ptr, length = wintypes.LPVOID(), wintypes.UINT()
    if not _version.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
            or length.value < 4:
        return ""
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
    key = rf"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
    if not _version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
        return ""
    return ctypes.wstring_at(ptr, length.value).rstrip("\0").strip()


def site_name(exe: str, title: str) -> str:
    """Site reconnu dans le titre d'une fenêtre de navigateur, sinon "" (le nom du navigateur s'applique)."""
    if exe.lower() not in _BROWSERS or not title:
        return ""
    for segment in _TITLE_SEP.split(title.strip()):
        if (name := _SITES.get(segment.strip().lower())):
            return name
    return ""


@functools.lru_cache(maxsize=256)
def display_name(exe: str, exe_path: str = "") -> str:
    exe = exe.lower()
    if not exe:
        return ""
    if exe in _KNOWN:
        return _KNOWN[exe]
    description = _file_description(exe_path) if exe_path else ""
    # Certaines descriptions sont des phrases (« Windows Explorer shell host… ») : trop longues pour une pastille.
    if description and len(description) <= 32:
        return description
    stem = PureWindowsPath(exe).stem
    return stem[:1].upper() + stem[1:]
