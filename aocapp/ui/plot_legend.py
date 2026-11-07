"""Plot legend samples with a visibility check box (GitHub #11)."""

from __future__ import annotations

import pyqtgraph as pg
from pyqtgraph.graphicsItems.LegendItem import ItemSample
from pyqtgraph.graphicsItems.ScatterPlotItem import drawSymbol
from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt

_HEIGHT = 20
_BOX = 12
_GAP = 6
_LINE = 28
_FALLBACK_FOREGROUND = "#7f7f7f"


class CheckableItemSample(ItemSample):
    """Check box left of the curve's line sample; a click shows or hides the curve.

    pyqtgraph's own sample already toggles the curve on click but draws an eye
    icon instead of the line. Here the check box reflects the curve's
    visibility and the line sample stays, faded while the curve is hidden.
    """

    show_checkbox = True

    def __init__(self, item) -> None:
        super().__init__(item)
        self.setFixedWidth(self._width())
        if self.show_checkbox:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Показать или скрыть кривую")

    @classmethod
    def _width(cls) -> int:
        return _BOX + _GAP + _LINE if cls.show_checkbox else _LINE

    def boundingRect(self) -> QtCore.QRectF:  # noqa: N802 - Qt API
        return QtCore.QRectF(0, 0, self._width(), _HEIGHT)

    @property
    def checked(self) -> bool:
        return self.item.isVisible()

    def _foreground(self) -> QtGui.QColor:
        """The legend text colour of the current theme."""
        parent = self.parentItem()
        while parent is not None and not isinstance(parent, pg.LegendItem):
            parent = parent.parentItem()
        color = parent.opts.get("labelTextColor") if parent is not None else None
        return pg.mkColor(color if color is not None else _FALLBACK_FOREGROUND)

    def paint(self, painter: QtGui.QPainter, *args) -> None:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        line_left = 0.0
        if self.show_checkbox:
            self._paint_checkbox(painter)
            line_left = _BOX + _GAP
        painter.save()
        painter.translate(line_left, 0)
        if not self.checked:
            painter.setOpacity(0.35)
        self._paint_line_sample(painter)
        painter.restore()

    def _paint_checkbox(self, painter: QtGui.QPainter) -> None:
        foreground = self._foreground()
        top = (_HEIGHT - _BOX) / 2
        box = QtCore.QRectF(0.75, top, _BOX, _BOX)
        painter.setPen(QtGui.QPen(foreground, 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 2, 2)
        if not self.checked:
            return
        mark = QtGui.QPainterPath()
        mark.moveTo(box.left() + 2.5, box.center().y() + 0.5)
        mark.lineTo(box.left() + 5.0, box.bottom() - 2.5)
        mark.lineTo(box.right() - 2.5, box.top() + 3.0)
        pen = QtGui.QPen(foreground, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(mark)

    def _paint_line_sample(self, painter: QtGui.QPainter) -> None:
        opts = self.item.opts
        middle = _HEIGHT / 2
        painter.setPen(pg.mkPen(opts["pen"]))
        painter.drawLine(QtCore.QPointF(1, middle), QtCore.QPointF(_LINE - 1, middle))
        symbol = opts.get("symbol")
        if symbol is None:
            return
        scatter = self.item.scatter.opts
        painter.translate(_LINE / 2, middle)
        drawSymbol(painter, symbol, scatter["size"], pg.mkPen(scatter["pen"]), pg.mkBrush(scatter["brush"]))


class PlainItemSample(CheckableItemSample):
    """The same line sample without a check box, for the exported PNG."""

    show_checkbox = False

    def mouseClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.ignore()
