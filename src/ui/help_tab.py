"""
Help: the user guide, inside the app.

Shows ``docs/GUIDE.md``, the same file people read on GitHub, so there is
one source of truth.  Qt renders the markdown; this page adds a contents
list, makes in-guide links (``#section``) jump to their heading, opens web
links in the browser, and scales screenshots to the available width.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QImage, QTextCursor, QTextImageFormat
from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from src import app_paths
from src.ui.icons import G
from src.ui.widgets import S4, S5, S6, Card, label


def docs_dir() -> str:
    return os.path.join(app_paths.resource_dir(), "docs")


def slug(text: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to -."""
    s = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return s.replace(" ", "-")


class HelpTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._headings: List[Tuple[int, str, int]] = []   # (level, text, position)
        self._images: List[Tuple[int, int]] = []          # (position, natural width)

        root = QVBoxLayout(self)
        root.setContentsMargins(S6, S5 + 4, S6, S5)
        root.setSpacing(S5)
        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(label("Help", "PageTitle"))
        head.addWidget(label("How to use every part of AMT, in plain language.",
                             "PageSubtitle", wrap=True))
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(S4)
        toc_card = Card("Contents", "", G.LIBRARY).grow()
        toc_card.setFixedWidth(250)
        self.toc = QListWidget()
        self.toc.setObjectName("HelpContents")
        self.toc.setWordWrap(True)
        self.toc.setSpacing(3)
        self.toc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toc.itemClicked.connect(self._on_toc)
        toc_card.body.addWidget(self.toc, 1)
        row.addWidget(toc_card)

        self.view = QTextBrowser()
        self.view.setObjectName("HelpView")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        # The contents list follows the reading position.
        self.view.verticalScrollBar().valueChanged.connect(self._sync_toc)
        row.addWidget(self.view, 1)
        root.addLayout(row, 1)
        self.load()

    # ------------------------------------------------------------------

    def load(self) -> bool:
        path = os.path.join(docs_dir(), "GUIDE.md")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            self.view.setPlainText("The user guide could not be found.\n\n"
                                   f"Expected it at: {path}")
            return False
        self.view.setSearchPaths([docs_dir()])
        self.view.setMarkdown(text)
        self._polish()
        self._index()
        self._fit_images()
        return True

    def _polish(self) -> None:
        """Comfortable reading: spacing between paragraphs and around
        headings, taller lines, and quiet table borders in theme colours.
        (Qt's markdown import has no CSS, so this is set per block.)"""
        from PyQt6.QtGui import QColor, QTextBlockFormat, QTextTableFormat
        from src.ui import theme
        c = theme.palette()
        doc = self.view.document()
        doc.setDocumentMargin(22)
        cursor = QTextCursor(doc)
        block = doc.begin()
        while block.isValid():
            fmt = QTextBlockFormat(block.blockFormat())
            level = fmt.headingLevel()
            if level:
                fmt.setTopMargin({1: 4, 2: 26, 3: 16}.get(level, 12))
                fmt.setBottomMargin(8)
            elif block.textList() is not None or block.text().strip():
                fmt.setBottomMargin(6 if block.textList() is not None else 10)
                fmt.setLineHeight(140, 1)       # 1 = ProportionalHeight
            cursor.setPosition(block.position())
            cursor.setBlockFormat(fmt)
            block = block.next()
        for frame in doc.rootFrame().childFrames():
            fmt = frame.frameFormat()
            if fmt.isTableFormat():
                tf = QTextTableFormat(fmt.toTableFormat())
                tf.setBorder(1)
                tf.setBorderBrush(QColor(c["border2"]))
                tf.setBorderCollapse(True)
                tf.setCellPadding(7)
                tf.setCellSpacing(0)
                tf.setTopMargin(4)
                tf.setBottomMargin(14)
                frame.setFrameFormat(tf)

    def _index(self) -> None:
        """Collect headings (for the contents) and images (for scaling)."""
        self._headings, self._images = [], []
        self.toc.clear()
        doc = self.view.document()
        block = doc.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level in (2, 3) and block.text().strip():
                self._headings.append((level, block.text().strip(), block.position()))
                item = QListWidgetItem(("      " if level == 3 else "") + block.text().strip())
                item.setData(Qt.ItemDataRole.UserRole, block.position())
                self.toc.addItem(item)
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    name = frag.charFormat().toImageFormat().name()
                    img = QImage(os.path.join(docs_dir(), name))
                    self._images.append((frag.position(), img.width() or 600))
                it += 1
            block = block.next()

    def _fit_images(self) -> None:
        """Show screenshots at most as wide as the reading area."""
        avail = max(200, self.view.viewport().width() - 40)
        doc = self.view.document()
        for pos, natural in self._images:
            cursor = QTextCursor(doc)
            cursor.setPosition(pos)
            cursor.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
            fmt = cursor.charFormat()
            if not fmt.isImageFormat():
                continue
            img = QTextImageFormat(fmt.toImageFormat())
            img.setWidth(min(natural, avail))
            img.setHeight(0)                    # keep the aspect ratio
            cursor.setCharFormat(img)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit_images()

    # ------------------------------------------------------------------

    def scroll_to_position(self, pos: int) -> None:
        doc = self.view.document()
        block = doc.findBlock(pos)
        top = doc.documentLayout().blockBoundingRect(block).top()
        self.view.verticalScrollBar().setValue(int(top))

    def heading_position(self, anchor: str) -> Optional[int]:
        for _level, text, pos in self._headings:
            if slug(text) == anchor:
                return pos
        return None

    def current_section(self) -> int:
        """Index (in the contents) of the section at the top of the view:
        the last heading that has scrolled to, or past, the top edge."""
        doc = self.view.document()
        layout = doc.documentLayout()
        top = self.view.verticalScrollBar().value() + 24      # a little slack
        current = 0
        for i, (_level, _text, pos) in enumerate(self._headings):
            if layout.blockBoundingRect(doc.findBlock(pos)).top() <= top:
                current = i
            else:
                break
        bar = self.view.verticalScrollBar()
        if bar.maximum() > 0 and bar.value() >= bar.maximum():
            # At the very bottom the last sections may never reach the top
            # edge; show the last one whose heading is visible.
            visible_bottom = bar.value() + self.view.viewport().height()
            for i, (_l, _t, pos) in enumerate(self._headings):
                if layout.blockBoundingRect(doc.findBlock(pos)).top() < visible_bottom:
                    current = i
        return current

    def _sync_toc(self, _value: int = 0) -> None:
        if not self._headings:
            return
        row = self.current_section()
        if self.toc.currentRow() != row:
            self.toc.setCurrentRow(row)          # does not emit itemClicked
            self.toc.scrollToItem(self.toc.item(row))

    def _on_toc(self, item: QListWidgetItem) -> None:
        self.scroll_to_position(item.data(Qt.ItemDataRole.UserRole))

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if url.hasFragment() and not url.path():
            pos = self.heading_position(url.fragment())
            if pos is not None:
                self.scroll_to_position(pos)
            return
        # Links to other repository files (README, LICENSE …): open them if
        # they exist next to the docs folder, as they do in a source checkout.
        target = os.path.normpath(os.path.join(docs_dir(), url.path()))
        if os.path.exists(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
