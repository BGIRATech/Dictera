"""Identité visuelle (spec § 2) : palette, typographie, feuille de style, icônes.

Une seule source pour les couleurs : les widgets dessinés à la main (graphiques,
pastilles) lisent les mêmes constantes que la feuille de style.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

BG = "#111416"  # fond
SURFACE = "#191E21"  # surfaces secondaires (cartes, menu)
SURFACE_HOVER = "#1F2528"
SEPARATOR = "#2A3235"
TEXT = "#F1F4F4"
TEXT_2 = "#929DA1"  # texte secondaire
ACCENT = "#6DA3AE"  # turquoise : données importantes et éléments interactifs
ACCENT_DARK = "#4E8591"  # fin du dégradé du bandeau d'accueil
ACCENT_SOFT = "rgba(109, 163, 174, 0.14)"  # rond des icônes, pastilles
DANGER = "#C9837B"  # actions destructrices uniquement (« Tout effacer »)

RADIUS = 8  # rayon modéré, cohérent partout
FONT = "Segoe UI Variable Text"
FONT_DISPLAY = "Segoe UI Variable Display"
ICON_FONT = "Segoe Fluent Icons"  # icônes fines en contour, natives de Windows 11


class Icon:
    """Glyphes Segoe Fluent Icons."""
    HOME = ""
    HISTORY = ""
    DICTIONARY = ""
    SETTINGS = ""
    COPY = ""
    DELETE = ""
    SEARCH = ""
    MIC = ""
    ADD = ""
    CLOSE = ""
    CHEVRON_DOWN = ""
    CHEVRON_UP = ""
    WORDS = ""
    LIBRARY = ""
    SPEED = ""
    STOPWATCH = ""
    LOCK = ""
    SHIELD = ""
    CHECK = ""
    WARNING = ""


def color(hex_or_rgba: str, alpha: float | None = None) -> QColor:
    c = QColor(hex_or_rgba)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    f = QFont(FONT_DISPLAY if display else FONT)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def icon_font(size: float) -> QFont:
    f = QFont(ICON_FONT)
    f.setPointSizeF(size)
    return f


def logo_pixmap(size: int, recording: bool = False) -> QPixmap:
    """Logo Dictera : onde sonore blanche dans un carré turquoise arrondi (spec § 3).
    Pendant l'enregistrement, les couleurs s'inversent (icône de la zone de notification)."""
    background, bars = (QColor(TEXT), QColor(ACCENT)) if recording else (QColor(ACCENT), QColor(TEXT))
    scale = 3
    s = size * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(background)
    p.drawRoundedRect(0, 0, s, s, s * 0.24, s * 0.24)
    heights = (0.30, 0.62, 1.0, 0.62, 0.30)
    bar_w, gap = s * 0.09, s * 0.06
    x = (s - (len(heights) * bar_w + (len(heights) - 1) * gap)) / 2
    p.setBrush(bars)
    for h in heights:
        bh = s * 0.56 * h
        p.drawRoundedRect(int(x), int((s - bh) / 2), int(bar_w), int(bh), bar_w / 2, bar_w / 2)
        x += bar_w + gap
    p.end()
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return pm


STYLESHEET = f"""
* {{ font-family: "{FONT}"; color: {TEXT}; }}
QWidget#Root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget#Page {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SURFACE}; border-right: 1px solid {SEPARATOR}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-family: "{FONT_DISPLAY}"; font-size: 20pt; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 11.5pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {TEXT_2}; font-size: 9.5pt; }}
QLabel[role="value"] {{ font-family: "{FONT_DISPLAY}"; font-size: 20pt; font-weight: 600; }}
QLabel[role="accent"] {{ color: {ACCENT}; font-size: 9.5pt; }}

QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {SEPARATOR}; border-radius: {RADIUS}px; }}
QFrame[separator="true"] {{ background: {SEPARATOR}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    background: transparent; border: 1px solid {SEPARATOR}; border-radius: 6px;
    padding: 6px 14px; font-size: 9.5pt;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: #3A4449; }}
QPushButton:pressed {{ background: {SEPARATOR}; }}
QPushButton:disabled {{ color: #5C6669; border-color: {SEPARATOR}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: {BG}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: #7DB2BC; border-color: #7DB2BC; }}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton[kind="danger"]:hover {{ border-color: {DANGER}; background: rgba(201, 131, 123, 0.08); }}
QPushButton[kind="chip"] {{ border-radius: 13px; padding: 0 14px; min-height: 28px; max-height: 28px; color: {TEXT_2}; }}
QPushButton[kind="chip"]:checked {{ color: {TEXT}; border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
QPushButton[kind="icon"] {{
    font-family: "{ICON_FONT}"; font-size: 10.5pt; border: none; padding: 4px; color: {TEXT_2};
    min-width: 26px; min-height: 26px; border-radius: 5px;
}}
QPushButton[kind="icon"]:hover {{ color: {TEXT}; background: {SURFACE_HOVER}; }}
QPushButton[kind="nav"] {{
    text-align: left; border: none; border-radius: 6px; padding: 9px 12px; font-size: 10pt; color: {TEXT_2};
}}
QPushButton[kind="nav"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[kind="nav"]:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QPushButton[kind="link"] {{ border: none; padding: 2px 0; color: {ACCENT}; font-size: 9pt; text-align: left; }}
QPushButton[kind="link"]:hover {{ color: #8CC0CA; background: transparent; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG}; border: 1px solid {SEPARATOR}; border-radius: 6px; padding: 6px 10px;
    font-size: 9.5pt; selection-background-color: {ACCENT}; selection-color: {BG};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[role="search"] {{ padding-left: 34px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {SEPARATOR}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; outline: none; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QTableWidget {{
    background: transparent; border: none; gridline-color: {SEPARATOR}; font-size: 9.5pt;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
}}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {SEPARATOR}; }}
QHeaderView::section {{
    background: transparent; color: {TEXT_2}; border: none; border-bottom: 1px solid {SEPARATOR};
    padding: 6px 8px; font-size: 9pt; text-align: left;
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SEPARATOR}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4449; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {SEPARATOR}; padding: 4px 8px; }}
QMessageBox {{ background: {SURFACE}; }}
QMessageBox QLabel {{ font-size: 10pt; }}
QMenu {{ background: {SURFACE}; border: 1px solid {SEPARATOR}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::item:disabled {{ color: {TEXT_2}; }}
QMenu::separator {{ height: 1px; background: {SEPARATOR}; margin: 4px 6px; }}
"""


def dark_title_bar(hwnd: int) -> None:
    """Barre de titre Windows 11 sombre et à la couleur du fond (DWM)."""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(on), ctypes.sizeof(on))  # mode sombre
        caption = ctypes.c_uint(0x00161411)  # COLORREF de #111416 (0x00BBGGRR)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(caption), ctypes.sizeof(caption))
    except (OSError, AttributeError):
        pass  # Windows 10 ou DWM indisponible : barre système standard
