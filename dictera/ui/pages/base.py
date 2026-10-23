"""Squelette commun des pages : zone défilante, marges généreuses, titre."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..context import UiContext
from ..widgets import label


class Page(QScrollArea):
    title = ""

    def __init__(self, ctx: UiContext):
        super().__init__()
        self.ctx = ctx
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        self.setWidget(inner)
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(40, 32, 40, 40)
        self.root.setSpacing(20)
        self.header = QHBoxLayout()
        self.header.addWidget(label(self.title, "title"))
        self.header.addStretch()
        self.root.addLayout(self.header)

    def refresh(self) -> None:
        """Relit les données ; appelé à l'affichage de la page et après chaque dictée."""

    @staticmethod
    def copy(text: str) -> None:
        QGuiApplication.clipboard().setText(text)
