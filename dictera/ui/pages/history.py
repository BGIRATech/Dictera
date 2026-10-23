"""Historique (spec § 5) : recherche, filtres, dictées regroupées par jour."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from ... import stats
from .. import theme as t
from ..context import UiContext
from ..widgets import Card, Combo, DictationRow, button, clear_layout, icon_label, label
from .base import Page

MAX_SHOWN = 500  # au-delà, affiner la recherche : l'interface reste fluide

_PERIODS = (("today", "Aujourd'hui"), ("7d", "7 jours"), ("all", "Tout"))


class HistoryPage(Page):
    title = "Historique"

    def __init__(self, ctx: UiContext):
        super().__init__(ctx)
        self.clear_btn = button("Tout effacer", "danger", self.confirm_clear)
        self.header.addWidget(self.clear_btn)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setProperty("role", "search")
        self.search.setPlaceholderText("Rechercher dans mes dictées")
        self.search.setClearButtonEnabled(True)
        loupe = icon_label(t.Icon.SEARCH, 10)
        loupe.setParent(self.search)
        loupe.move(12, 8)
        self._debounce = QTimer(self, singleShot=True, interval=200, timeout=self.refresh)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        bar.addWidget(self.search, 1)
        self.period = QButtonGroup(self)
        for i, (key, text) in enumerate(_PERIODS):
            chip = button(text, "chip")
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.setProperty("period", key)
            self.period.addButton(chip, i)
            bar.addWidget(chip)
        self.period.buttonClicked.connect(lambda _b: self.refresh())
        self.app_filter = Combo()
        self.app_filter.setMinimumWidth(170)
        self.app_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.app_filter)
        self.root.addLayout(bar)

        self.results = QVBoxLayout()
        self.results.setSpacing(16)
        self.root.addLayout(self.results)
        self.root.addStretch()

    def _reload_apps(self) -> None:
        current = self.app_filter.currentData()
        self.app_filter.blockSignals(True)
        self.app_filter.clear()
        self.app_filter.addItem("Toutes les applis", None)
        for name in self.ctx.db.apps():
            self.app_filter.addItem(name, name)
        idx = self.app_filter.findData(current)
        self.app_filter.setCurrentIndex(max(idx, 0))
        self.app_filter.blockSignals(False)

    def refresh(self) -> None:
        self._reload_apps()
        period = self.period.checkedButton().property("period")
        groups = stats.history(self.ctx.db, period, app=self.app_filter.currentData(), search=self.search.text())
        clear_layout(self.results)
        shown = 0
        for day_label, items in groups:
            if shown >= MAX_SHOWN:
                break
            card = Card(spacing=0)
            head = QHBoxLayout()
            head.addWidget(label(day_label, "section"))
            head.addStretch()
            words = sum(d.words for d in items)
            head.addWidget(label(f"{len(items)} dictée{'s' if len(items) > 1 else ''} · {words} mots", "muted"))
            card.body.addLayout(head)
            for d in items[: MAX_SHOWN - shown]:
                row = DictationRow(d, detailed=True)
                row.copy_requested.connect(self.copy)
                row.delete_requested.connect(self.delete)
                card.body.addWidget(row)
            shown += len(items)
            self.results.addWidget(card)
        if not groups:
            empty = "Aucune dictée ne correspond." if self.search.text() or period != "all" or \
                self.app_filter.currentData() else "Aucune dictée pour l'instant."
            self.results.addWidget(label(empty, "muted"))
        elif shown >= MAX_SHOWN:
            self.results.addWidget(label(f"{MAX_SHOWN} dictées affichées : affinez la recherche pour voir les autres.",
                                         "muted"))
        self.clear_btn.setEnabled(bool(self.ctx.db.apps()) or bool(groups))

    def delete(self, dictation_id: int) -> None:
        self.ctx.db.delete_dictation(dictation_id)
        self._notify()

    def confirm_clear(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Tout effacer")
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setText("Effacer tout l'historique des dictées ?")
        box.setInformativeText("Les textes sont supprimés définitivement de ce PC. "
                               "Le dictionnaire et les corrections sont conservés.")
        ok = box.addButton("Tout effacer", QMessageBox.ButtonRole.DestructiveRole)
        ok.setProperty("kind", "danger")
        box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is ok:
            self.clear_all()

    def clear_all(self) -> None:
        self.ctx.db.clear_history()
        self._notify()

    def _notify(self) -> None:
        for listener in self.ctx.listeners:
            listener()
