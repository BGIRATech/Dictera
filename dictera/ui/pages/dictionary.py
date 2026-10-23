"""Dictionnaire (spec § 6) : mes mots (amorce de Whisper) et corrections automatiques."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLayout, QLineEdit, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QWidget)

from ... import stats
from .. import theme as t
from ..context import UiContext
from ..widgets import Card, IconBadge, button, clear_layout, icon_button, label
from .base import Page


class FlowLayout(QLayout):
    """Disposition en lignes qui passent à la ligne : les mots en étiquettes."""

    def __init__(self, spacing: int = 8):
        super().__init__()
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, apply):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class WordChip(QWidget):
    def __init__(self, word: str, on_remove):
        super().__init__()
        self.setObjectName("chip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"#chip {{ background: {t.BG}; border: 1px solid {t.SEPARATOR}; border-radius: 14px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 2, 4, 2)
        lay.setSpacing(2)
        lay.addWidget(label(word))
        rm = icon_button(t.Icon.CLOSE, f"Retirer « {word} »", lambda: on_remove(word))
        rm.setStyleSheet("font-size: 7pt; min-width: 22px; min-height: 22px;")
        lay.addWidget(rm)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class DictionaryPage(Page):
    title = "Dictionnaire"

    def __init__(self, ctx: UiContext):
        super().__init__(ctx)
        top = Card()
        row = QHBoxLayout()
        row.setSpacing(40)
        self.n_words = label("—", "value")
        self.n_corr = label("—", "value")
        for badge, value, caption in ((t.Icon.DICTIONARY, self.n_words, "mots dans mon dictionnaire"),
                                      (t.Icon.CHECK, self.n_corr, "corrections appliquées cette semaine")):
            block = QHBoxLayout()
            block.setSpacing(14)
            block.addWidget(IconBadge(badge, 40))
            col = QHBoxLayout()
            col.setSpacing(8)
            col.addWidget(value)
            col.addWidget(label(caption, "muted"))
            block.addLayout(col)
            row.addLayout(block)
        row.addStretch()
        top.body.addLayout(row)
        top.body.addWidget(label("Tout reste sur ce PC : les mots guident la transcription locale, "
                                 "les corrections s'appliquent après, sans réseau.", "muted"))
        self.root.addWidget(top)

        words = Card()
        words.body.addWidget(label("Mes mots à moi", "section"))
        words.body.addWidget(label("Noms, marques, jargon : Whisper les reconnaît mieux à chaque dictée.", "muted"))
        add = QHBoxLayout()
        self.word_input = QLineEdit()
        self.word_input.setPlaceholderText("Ajouter un mot ou une expression")
        self.word_input.returnPressed.connect(self.add_word)
        add.addWidget(self.word_input, 1)
        add.addWidget(button("Ajouter", "primary", self.add_word))
        words.body.addLayout(add)
        self.chips_host = QWidget()
        self.chips = FlowLayout()
        self.chips_host.setLayout(self.chips)
        words.body.addWidget(self.chips_host)
        self.root.addWidget(words)

        corr = Card()
        corr.body.addWidget(label("Corrections automatiques", "section"))
        corr.body.addWidget(label("Appliquées en local après chaque transcription, mot entier, sans tenir "
                                  "compte de la casse.", "muted"))
        add2 = QHBoxLayout()
        self.heard = QLineEdit()
        self.heard.setPlaceholderText("Ce qui est entendu (ex. ski)")
        self.written = QLineEdit()
        self.written.setPlaceholderText("Ce qui doit s'écrire (ex. skill)")
        self.written.returnPressed.connect(self.add_correction)
        arrow = label("→", "muted")
        add2.addWidget(self.heard, 1)
        add2.addWidget(arrow)
        add2.addWidget(self.written, 1)
        add2.addWidget(button("Ajouter", "primary", self.add_correction))
        corr.body.addLayout(add2)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Ce qui est entendu", "Ce qui doit s'écrire", ""])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.setColumnWidth(2, 44)
        self.table.itemChanged.connect(self._edited)
        corr.body.addWidget(self.table)
        self.error = label("", "accent")
        corr.body.addWidget(self.error)
        self.root.addWidget(corr)
        self.root.addStretch()

    def refresh(self) -> None:
        db = self.ctx.db
        ds = stats.dictionary(db)
        self.n_words.setText(str(ds.words))
        self.n_corr.setText(str(ds.corrections_this_week))
        clear_layout(self.chips)
        for w in db.words():
            self.chips.addWidget(WordChip(w, self.remove_word))
        if not db.words():
            self.chips.addWidget(label("Aucun mot pour l'instant.", "muted"))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for heard, written in db.corrections().items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            h = QTableWidgetItem(heard)
            h.setData(Qt.ItemDataRole.UserRole, heard)
            self.table.setItem(r, 0, h)
            self.table.setItem(r, 1, QTableWidgetItem(written))
            self.table.setCellWidget(r, 2, icon_button(t.Icon.DELETE, "Supprimer cette correction",
                                                       lambda h=heard: self.remove_correction(h)))
            self.table.setRowHeight(r, 38)
        self.table.setFixedHeight(36 + 38 * max(self.table.rowCount(), 1))
        self.table.blockSignals(False)

    def add_word(self) -> None:
        if self.ctx.db.add_word(self.word_input.text()):
            self.word_input.clear()
            self._changed()

    def remove_word(self, word: str) -> None:
        self.ctx.db.remove_word(word)
        self._changed()

    def add_correction(self) -> None:
        try:
            self.ctx.db.set_correction(self.heard.text(), self.written.text())
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.error.setText("")
        self.heard.clear()
        self.written.clear()
        self._changed()

    def remove_correction(self, heard: str) -> None:
        self.ctx.db.remove_correction(heard)
        self._changed()

    def _edited(self, item: QTableWidgetItem) -> None:
        """Édition en place (double-clic) d'une correction existante."""
        r = item.row()
        old = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
        heard, written = self.table.item(r, 0).text(), self.table.item(r, 1).text()
        try:
            if fold_eq(old, heard):
                self.ctx.db.set_correction(old, written)
            else:
                self.ctx.db.set_correction(heard, written)
                self.ctx.db.remove_correction(old)
        except ValueError as e:
            self.error.setText(str(e))
        self._changed()

    def _changed(self) -> None:
        self.ctx.on_vocabulary_changed()
        self.refresh()


def fold_eq(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()
