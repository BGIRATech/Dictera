"""Tableau de bord (spec § 4)."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import stats
from .. import theme as t
from ..context import UiContext, first_name
from ..widgets import AppBars, Card, DailyBars, DictationRow, Flame, StatCard, clear_layout, label
from .base import Page


class Banner(QWidget):
    """Bandeau d'accueil turquoise en dégradé, petite onde sonore à droite."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(112)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(4)
        self.hello = label("")
        self.hello.setFont(t.font(18, QFont.Weight.DemiBold, display=True))
        self.hello.setStyleSheet(f"color: {t.BG};")
        self.hint = label("")
        self.hint.setStyleSheet("color: rgba(17, 20, 22, 0.78); font-size: 10pt;")
        lay.addWidget(self.hello)
        lay.addWidget(self.hint)

    def set(self, name: str, key: str) -> None:
        self.hello.setText(f"Salut {name}")
        self.hint.setText(f"Maintenez {key}, parlez, relâchez : le texte s'écrit là où vous étiez.")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor(t.ACCENT))
        g.setColorAt(1, QColor(t.ACCENT_DARK))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, t.RADIUS, t.RADIUS)
        # Onde sonore : barres fines, blanches et translucides.
        heights = (0.22, 0.42, 0.7, 0.5, 0.86, 0.58, 0.34, 0.62, 0.4, 0.2)
        x = r.right() - 32 - len(heights) * 9
        p.setPen(QPen(t.color(t.TEXT, 0.75), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for h in heights:
            bh = r.height() * 0.5 * h
            p.drawLine(int(x), int(r.center().y() - bh / 2), int(x), int(r.center().y() + bh / 2))
            x += 9


class DashboardPage(Page):
    title = "Tableau de bord"

    def __init__(self, ctx: UiContext):
        super().__init__(ctx)
        self.banner = Banner()
        self.root.addWidget(self.banner)

        cards = QGridLayout()
        cards.setSpacing(16)
        self.c_today = StatCard(t.Icon.WORDS, "Mots dictés aujourd'hui")
        self.c_total = StatCard(t.Icon.LIBRARY, "Total des mots")
        self.c_speed = StatCard(t.Icon.SPEED, "Vitesse moyenne")
        self.c_saved = StatCard(t.Icon.STOPWATCH, "Temps gagné")
        for i, c in enumerate((self.c_today, self.c_total, self.c_speed, self.c_saved)):
            cards.addWidget(c, 0, i)
        self.root.addLayout(cards)

        charts = QHBoxLayout()
        charts.setSpacing(16)
        daily = Card()
        head = QHBoxLayout()
        head.addWidget(label("Mots dictés par jour", "section"))
        head.addStretch()
        head.addWidget(Flame())
        self.streak = label("", "muted")
        head.addWidget(self.streak)
        daily.body.addLayout(head)
        daily.body.addWidget(label("14 derniers jours", "muted"))
        self.bars = DailyBars()
        daily.body.addWidget(self.bars)
        apps = Card()
        apps.body.addWidget(label("Où je dicte", "section"))
        apps.body.addWidget(label("Part des mots, top 5 des applis", "muted"))
        apps.body.addSpacing(6)
        self.apps = AppBars()
        apps.body.addWidget(self.apps)
        apps.body.addStretch()
        charts.addWidget(daily, 3)
        charts.addWidget(apps, 2)
        self.root.addLayout(charts)

        recent = Card(spacing=0)
        recent.body.addWidget(label("Mes 5 dernières dictées", "section"))
        self.recent = QVBoxLayout()
        self.recent.setSpacing(0)
        recent.body.addLayout(self.recent)
        self.root.addWidget(recent)
        self.root.addStretch()

    def refresh(self) -> None:
        cfg = self.ctx.config
        s = stats.dashboard(self.ctx.db, cfg.typing_wpm)
        self.banner.set(first_name(cfg), cfg.hotkey_label)
        if s.delta_pct is None:
            delta = "première journée de dictée" if s.words_today and not s.words_yesterday else "rien hier pour comparer"
            self.c_today.set(f"{s.words_today:,}".replace(",", " "), delta)
        else:
            self.c_today.set(f"{s.words_today:,}".replace(",", " "), f"{s.delta_pct:+.0f} % vs hier", sub_accent=True)
        self.c_total.set(f"{s.total_words:,}".replace(",", " "),
                         f"{s.total_dictations} dictée{'s' if s.total_dictations > 1 else ''}")
        self.c_speed.set(f"{s.avg_wpm:.0f}", "mots par minute")
        self.c_saved.set(s.time_saved_label, f"vs {cfg.typing_wpm} mots/min au clavier")
        self.bars.set_data(s.daily)
        self.streak.setText(f"{s.streak_days} jour{'s' if s.streak_days > 1 else ''} d'affilée")
        self.apps.set_data([(a.app_name, a.pct) for a in s.top_apps])
        clear_layout(self.recent)
        if not s.recent:
            self.recent.addSpacing(10)
            self.recent.addWidget(label(f"Aucune dictée pour l'instant. Maintenez {cfg.hotkey_label} et parlez.",
                                        "muted"))
        for d in s.recent:
            row = DictationRow(d)
            row.copy_requested.connect(self.copy)
            self.recent.addWidget(row)
