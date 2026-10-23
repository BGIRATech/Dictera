"""Composants partagés par les 4 pages. Les graphiques sont dessinés à la main
(QPainter) pour suivre exactement la palette : lignes fines, turquoise réservé aux données."""

from datetime import date
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QToolTip, QVBoxLayout, QWidget)

from . import theme as t
from ..storage import Dictation

_DAY_SHORT = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
_DAY_LONG = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTH_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
               "octobre", "novembre", "décembre"]


def _compact(n: int) -> str:
    """Valeur au-dessus d'une barre étroite : 1 234 -> 1,2k."""
    return str(n) if n < 1000 else f"{n / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "k"


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


def button(text: str, kind: str | None = None, on_click: Callable | None = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def icon_button(glyph: str, tooltip: str, on_click: Callable | None = None) -> QPushButton:
    return button(glyph, "icon", on_click, tooltip)


def separator() -> QFrame:
    f = QFrame()
    f.setProperty("separator", True)
    return f


class Card(QFrame):
    def __init__(self, margins: int = 20, spacing: int = 12):
        super().__init__()
        self.setProperty("card", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class IconBadge(QWidget):
    """Icône fine dans un rond turquoise clair (cartes de chiffres clés)."""

    def __init__(self, glyph: str, size: int = 36):
        super().__init__()
        self.glyph = glyph
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(t.ACCENT, 0.14))
        p.drawEllipse(self.rect())
        p.setPen(QColor(t.ACCENT))
        p.setFont(t.icon_font(self.width() * 0.30))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.glyph)


class StatCard(Card):
    """Carte de chiffre clé : icône, libellé, valeur, ligne secondaire."""

    def __init__(self, glyph: str, caption: str):
        super().__init__(margins=18, spacing=6)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconBadge(glyph))
        head.addWidget(label(caption, "muted"))
        head.addStretch()
        self.body.addLayout(head)
        self.body.addSpacing(6)
        self.value = label("—", "value")
        self.sub = label("", "muted")
        self.body.addWidget(self.value)
        self.body.addWidget(self.sub)

    def set(self, value: str, sub: str = "", sub_accent: bool = False) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setProperty("role", "accent" if sub_accent else "muted")
        self.sub.style().unpolish(self.sub)
        self.sub.style().polish(self.sub)


def icon_label(glyph: str, size: float = 10.5, color: str = t.TEXT_2) -> QLabel:
    """Glyphe d'icône dans un QLabel. La police passe par la feuille de style : la règle
    globale « * { font-family } » écraserait un simple setFont()."""
    w = QLabel(glyph)
    w.setStyleSheet(icon_style(size, color))
    return w


def icon_style(size: float, color: str) -> str:
    return f'font-family: "{t.ICON_FONT}"; font-size: {size}pt; color: {color};'


class Pill(QLabel):
    """Pastille turquoise portant le nom de l'appli."""

    HEIGHT = 20

    def __init__(self, text: str):
        super().__init__(text or "Inconnue")
        # Qt ignore un rayon supérieur à la demi-hauteur : hauteur fixe, rayon juste en dessous.
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(f"background: {t.ACCENT_SOFT}; color: {t.ACCENT}; border-radius: {self.HEIGHT // 2 - 1}px;"
                           " padding: 0 10px; font-size: 8.5pt; font-weight: 600;")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Combo(QComboBox):
    """Liste déroulante avec un chevron fin dessiné (la flèche native est masquée)."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(t.TEXT_2 if self.isEnabled() else "#5C6669"), 1.4,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() - 16, self.height() / 2
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class ElidedText(QWidget):
    """Texte sur `max_lines` lignes au plus, terminé par « … » s'il déborde."""

    def __init__(self, text: str = "", max_lines: int = 2, muted: bool = False):
        super().__init__()
        self._text = text
        self.max_lines = max_lines
        self.muted = muted
        self.setFont(t.font(9.5))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def _lines(self, width: float) -> list[tuple[str, float]]:
        layout = QTextLayout(self._text, self.font())
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(opt)
        lines, y = [], 0.0
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines.append((line.textStart(), line.textLength()))
        layout.endLayout()
        fm = QFontMetricsF(self.font())
        out = []
        for i, (start, length) in enumerate(lines[: self.max_lines]):
            chunk = self._text[start:start + length].rstrip("\n")
            if i == self.max_lines - 1 and len(lines) > self.max_lines:
                chunk = fm.elidedText(self._text[start:], Qt.TextElideMode.ElideRight, width)
            out.append((chunk, y))
            y += fm.lineSpacing()
        return out

    def heightForWidth(self, width: int) -> int:
        n = max(1, len(self._lines(max(width, 50))))
        return int(QFontMetricsF(self.font()).lineSpacing() * n) + 2

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self) -> QSize:
        return QSize(300, self.heightForWidth(300))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QColor(t.TEXT_2 if self.muted else t.TEXT))
        p.setFont(self.font())
        ascent = QFontMetricsF(self.font()).ascent()
        for chunk, y in self._lines(self.width()):
            p.drawText(QPointF(0, y + ascent), chunk)


class Toggle(QAbstractButton):
    """Interrupteur marche/arrêt."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(t.ACCENT if on else "#3A4449"), 1))
        p.setBrush(QColor(t.ACCENT) if on else QColor(t.BG))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 8
        x = r.right() - d - 4 if on else r.left() + 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.BG if on else t.TEXT_2))
        p.drawEllipse(QRectF(x, r.top() + 4, d, d))


class Badge(QLabel):
    """Badge d'état : point + texte (« Local · large-v3-turbo, CUDA »)."""

    def __init__(self, text: str, ok: bool = True):
        super().__init__()
        self.set(text, ok)

    def set(self, text: str, ok: bool = True) -> None:
        c = t.ACCENT if ok else t.TEXT_2
        self.setText(f"<span style='color:{c}'>●</span>&nbsp; {text}")
        bg = t.ACCENT_SOFT if ok else "rgba(146,157,161,0.10)"
        self.setStyleSheet(f"background: {bg}; border-radius: 11px; padding: 3px 11px; font-size: 9pt;")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Flame(QWidget):
    """Petite flamme de la série de jours d'affilée."""

    def __init__(self, size: int = 16):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Flamme extérieure : pointe haute légèrement déportée, flanc gauche avec une
        # langue secondaire, base arrondie.
        outer = QPainterPath(QPointF(w * 0.54, h * 0.02))
        outer.cubicTo(w * 0.60, h * 0.22, w * 0.90, h * 0.40, w * 0.88, h * 0.66)
        outer.cubicTo(w * 0.86, h * 0.88, w * 0.70, h * 0.98, w * 0.50, h * 0.98)
        outer.cubicTo(w * 0.28, h * 0.98, w * 0.12, h * 0.84, w * 0.12, h * 0.64)
        outer.cubicTo(w * 0.12, h * 0.46, w * 0.24, h * 0.36, w * 0.30, h * 0.26)
        outer.cubicTo(w * 0.34, h * 0.40, w * 0.40, h * 0.44, w * 0.44, h * 0.44)
        outer.cubicTo(w * 0.42, h * 0.28, w * 0.48, h * 0.12, w * 0.54, h * 0.02)
        inner = QPainterPath(QPointF(w * 0.50, h * 0.52))
        inner.cubicTo(w * 0.62, h * 0.64, w * 0.68, h * 0.72, w * 0.66, h * 0.82)
        inner.cubicTo(w * 0.64, h * 0.92, w * 0.36, h * 0.92, w * 0.34, h * 0.80)
        inner.cubicTo(w * 0.33, h * 0.70, w * 0.42, h * 0.64, w * 0.50, h * 0.52)
        p.setPen(QPen(QColor(t.ACCENT), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(t.color(t.ACCENT, 0.16))
        p.drawPath(outer)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(t.ACCENT, 0.75))
        p.drawPath(inner)


class DailyBars(QWidget):
    """Histogramme des mots par jour : valeur au-dessus de chaque barre, jour de la semaine
    et date (jj/mm) sous chaque barre, date complète au survol."""

    def __init__(self):
        super().__init__()
        self.data: list[tuple[str, int]] = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(210)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self.data = data
        self.update()

    def _geometry(self):
        n = max(len(self.data), 1)
        left, right, top, bottom = 4, 4, 22, 40
        slot = (self.width() - left - right) / n
        return left, top, bottom, slot

    def mouseMoveEvent(self, e):
        left, _top, _bottom, slot = self._geometry()
        i = int((e.position().x() - left) // slot) if slot else -1
        i = i if 0 <= i < len(self.data) else -1
        if i != self.hover:
            self.hover = i
            self.update()
            if i >= 0:
                day, words = self.data[i]
                d = date.fromisoformat(day)
                when = "Aujourd'hui" if i == len(self.data) - 1 else _DAY_LONG[d.weekday()].capitalize()
                QToolTip.showText(e.globalPosition().toPoint(),
                                  f"{when} {d.day} {_MONTH_LONG[d.month - 1]} · {words} mot{'s' if words > 1 else ''}",
                                  self)

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def paintEvent(self, _e):
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, bottom, slot = self._geometry()
        h = self.height() - top - bottom
        peak = max(w for _, w in self.data) or 1
        base_y = top + h
        p.setPen(QPen(QColor(t.SEPARATOR), 1))
        p.drawLine(QPointF(left, base_y + 0.5), QPointF(self.width() - 4, base_y + 0.5))
        bar_w = min(slot * 0.56, 26)
        small = t.font(8)
        fm = QFontMetricsF(small)
        # Fenêtre étroite : une date sur deux (en partant d'aujourd'hui) pour éviter les chevauchements.
        step = 1 if fm.horizontalAdvance("00/00") + 6 <= slot else 2
        last = len(self.data) - 1
        for i, (day, words) in enumerate(self.data):
            cx = left + slot * i + slot / 2
            bh = max(h * words / peak, 2 if words else 0)
            rect = QRectF(cx - bar_w / 2, base_y - bh, bar_w, bh)
            hovered = i == self.hover
            is_today = i == last
            if words:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#8CC0CA") if hovered else QColor(t.ACCENT))
                path = QPainterPath()
                path.addRoundedRect(rect, 3, 3)
                p.drawPath(path)
                p.setFont(t.font(8, QFont.Weight.DemiBold) if hovered else small)
                p.setPen(QColor(t.TEXT if hovered else t.TEXT_2))
                p.drawText(QRectF(cx - slot / 2, rect.top() - 18, slot, 16), Qt.AlignmentFlag.AlignCenter,
                           _compact(words))
            if (last - i) % step:
                continue
            d = date.fromisoformat(day)
            p.setFont(t.font(8, QFont.Weight.DemiBold) if is_today else small)
            p.setPen(QColor(t.TEXT if is_today or hovered else t.TEXT_2))
            p.drawText(QRectF(cx - slot / 2 - 4, base_y + 5, slot + 8, 15), Qt.AlignmentFlag.AlignCenter,
                       "auj." if is_today else _DAY_SHORT[d.weekday()])
            p.setFont(small)
            p.setPen(QColor(t.TEXT_2))
            p.drawText(QRectF(cx - slot / 2 - 4, base_y + 20, slot + 8, 15), Qt.AlignmentFlag.AlignCenter,
                       f"{d.day:02d}/{d.month:02d}")


class AppBars(QWidget):
    """« Où je dicte » : barres horizontales, % des mots par appli."""

    ROW = 34

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, float]] = []

    def set_data(self, rows: list[tuple[str, float]]) -> None:
        self.rows = rows
        self.setMinimumHeight(max(1, len(rows)) * self.ROW)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            p.setPen(QColor(t.TEXT_2))
            p.setFont(t.font(9.5))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "Aucune dictée pour l'instant.")
            return
        name_w, pct_w = 110, 52
        track_x = name_w
        track_w = self.width() - name_w - pct_w
        for i, (name, pct) in enumerate(self.rows):
            y = i * self.ROW + self.ROW / 2
            p.setFont(t.font(9.5))
            p.setPen(QColor(t.TEXT))
            fm = QFontMetricsF(p.font())
            p.drawText(QRectF(0, y - 10, name_w - 10, 20), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, name_w - 12))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.SEPARATOR))
            p.drawRoundedRect(QRectF(track_x, y - 3, track_w, 6), 3, 3)
            p.setBrush(QColor(t.ACCENT))
            p.drawRoundedRect(QRectF(track_x, y - 3, max(track_w * pct / 100, 6), 6), 3, 3)
            p.setPen(QColor(t.TEXT_2))
            p.drawText(QRectF(track_x + track_w, y - 10, pct_w, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{pct:.0f} %")


class DictationRow(QFrame):
    """Une dictée : heure, pastille d'appli, mots (et vitesse), texte sur 2 lignes,
    copier ; en mode historique : transcription brute dépliable et supprimer."""

    copy_requested = Signal(str)
    delete_requested = Signal(int)

    def __init__(self, d: Dictation, detailed: bool = False):
        super().__init__()
        self.d = d
        self.setStyleSheet(f"DictationRow {{ border-bottom: 1px solid {t.SEPARATOR}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 12)
        root.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label(d.time_hhmm, "muted"))
        head.addWidget(Pill(d.app_name))
        meta = f"{d.words} mot{'s' if d.words > 1 else ''}"
        if detailed:
            meta += f" · {d.wpm:.0f} mots/min"
        head.addWidget(label(meta, "muted"))
        head.addStretch()
        head.addWidget(icon_button(t.Icon.COPY, "Copier le texte", lambda: self.copy_requested.emit(d.final_text)))
        if detailed:
            head.addWidget(icon_button(t.Icon.DELETE, "Supprimer cette dictée",
                                       lambda: self.delete_requested.emit(d.id)))
        root.addLayout(head)
        root.addWidget(ElidedText(d.final_text, max_lines=2 if not detailed else 6))
        if detailed and d.raw_text and d.raw_text != d.final_text:
            self.raw = ElidedText(d.raw_text, max_lines=20, muted=True)
            self.raw.hide()
            self.toggle = button("Transcription brute ▾", "link", self._toggle_raw)
            root.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
            root.addWidget(self.raw)

    def _toggle_raw(self) -> None:
        shown = not self.raw.isVisible()
        self.raw.setVisible(shown)
        self.toggle.setText("Transcription brute " + ("▴" if shown else "▾"))


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def h_row(*widgets, spacing: int = 10, stretch_at: int | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if stretch_at == i:
            row.addStretch()
        if isinstance(w, QWidget):
            row.addWidget(w)
        else:
            row.addLayout(w)
    if stretch_at is not None and stretch_at >= len(widgets):
        row.addStretch()
    return row


def mixed_font_text(btn: QPushButton, glyph: str, text: str) -> None:
    """Bouton avec une icône Fluent suivie d'un libellé (deux polices)."""
    btn.setText("")
    lay = QHBoxLayout(btn)
    lay.setContentsMargins(12, 0, 12, 0)
    lay.setSpacing(12)
    ic = icon_label(glyph)
    ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    tx = QLabel(text)
    tx.setFont(t.font(10))
    tx.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    lay.addWidget(ic)
    lay.addWidget(tx)
    lay.addStretch()
    btn.setMinimumHeight(38)
    btn._labels = (ic, tx)  # couleur ajustée selon l'état (voir Sidebar)
