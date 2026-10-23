"""Fenêtre principale : menu de gauche (logo + 4 pages) et pages empilées.

Fermer la fenêtre la masque : Dictera continue de tourner dans la zone de notification.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from .. import APP_NAME
from . import theme as t
from .context import UiContext
from .pages.dashboard import DashboardPage
from .pages.dictionary import DictionaryPage
from .pages.history import HistoryPage
from .pages.settings import SettingsPage
from .widgets import button, icon_style, label, mixed_font_text

NAV = ((t.Icon.HOME, "Tableau de bord", DashboardPage), (t.Icon.HISTORY, "Historique", HistoryPage),
       (t.Icon.DICTIONARY, "Dictionnaire", DictionaryPage), (t.Icon.SETTINGS, "Réglages", SettingsPage))


class Sidebar(QWidget):
    def __init__(self, on_select):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(232)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 22, 16, 18)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(t.logo_pixmap(34))
        brand.addWidget(logo)
        name = label(APP_NAME)
        name.setFont(t.font(14, QFont.Weight.DemiBold, display=True))
        brand.addWidget(name)
        brand.addStretch()
        lay.addLayout(brand)
        lay.addSpacing(26)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, (glyph, text, _page) in enumerate(NAV):
            b = button("", "nav")
            b.setCheckable(True)
            mixed_font_text(b, glyph, text)
            b.toggled.connect(lambda checked, b=b: self._style(b, checked))
            self.group.addButton(b, i)
            self.buttons.append(b)
            self._style(b, False)
            lay.addWidget(b)
        self.group.idClicked.connect(on_select)
        lay.addStretch()
        self.status = label("", "muted", wrap=True)
        lay.addWidget(self.status)

    @staticmethod
    def _style(b, checked: bool) -> None:
        icon, text = b._labels
        icon.setStyleSheet(icon_style(10.5, t.ACCENT if checked else t.TEXT_2))
        text.setStyleSheet(f"color: {t.TEXT if checked else t.TEXT_2};"
                           f" font-weight: {'600' if checked else '400'};")

    def select(self, i: int) -> None:
        self.buttons[i].setChecked(True)


class MainWindow(QMainWindow):
    def __init__(self, ctx: UiContext):
        super().__init__()
        self.ctx = ctx
        self.quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(t.logo_pixmap(64)))
        self.resize(1200, 820)
        self.setMinimumSize(1000, 680)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar(self.show_page)
        self.stack = QStackedWidget()
        self.pages = [cls(ctx) for _glyph, _text, cls in NAV]
        for p in self.pages:
            self.stack.addWidget(p)
        lay.addWidget(self.sidebar)
        lay.addWidget(self.stack, 1)
        ctx.listeners.append(self.refresh_current)
        self.show_page(0)  # spec § 9 : au lancement, le Tableau de bord

    def show_page(self, i: int) -> None:
        self.sidebar.select(i)
        self.stack.setCurrentIndex(i)
        self.pages[i].refresh()

    def refresh_current(self) -> None:
        """Après une dictée ou une suppression : seule la page visible est relue."""
        page = self.stack.currentWidget()
        if self.isVisible() and page is not None:
            page.refresh()

    def set_status(self, text: str) -> None:
        self.sidebar.status.setText(text)

    def bring_to_front(self) -> None:
        self.show_page(self.stack.currentIndex())
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        t.dark_title_bar(int(self.winId()))

    def closeEvent(self, e):
        if self.quitting:
            e.accept()
            return
        e.ignore()  # fermer = masquer ; « Quitter » est dans la zone de notification
        self.hide()
