"""Exercise PNG export and native Qt destruction in a disposable process."""

from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import shiboken6
from PIL import Image
from PySide6 import QtCore, QtWidgets

from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.s21_models import S21Result
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True)
    app = QtWidgets.QApplication([])
    QtCore.QCoreApplication.setOrganizationName("AOCappPNGLifecycleTests")
    QtCore.QCoreApplication.setApplicationName("AOCappPNGLifecycleTests")
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(directory))
    for iteration in range(40):
        gc.collect()
        use_case = Mock()
        use_case.execute.return_value = S21Result([100, 300, 500, 700, 900], [-18, -8, -4, -7, -15])
        window = MainWindow(GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()), use_case)
        window.show()
        app.processEvents()
        window._s21_output.clear()
        for _ in range(5):
            window._run_s21()
            deadline = time.monotonic() + 5
            while window._s21_thread is not None and time.monotonic() < deadline:
                app.processEvents()
            assert window._s21_thread is None
            assert window._s21_worker is None
            assert window._run_s21_button.isEnabled()
        window._plot_scale_inputs["x_max"].setValue(1100)
        window._apply_plot_scale()
        vb = window._plot.getPlotItem().vb
        window._on_plot_mouse_moved(vb.mapToScene(vb.boundingRect().center()))
        app.processEvents()
        original_range = vb.viewRange()
        for repeat in range(2):
            path = directory / f"график-{iteration}-{repeat}.png"
            window.export_plot_to_path(path)
            with Image.open(path) as png:
                assert png.format == "PNG"
                assert png.width >= 1200 and png.height > 0
                # Ensure real theory data, rather than a blank white image.
                colors = dict((color, count) for count, color in png.convert("RGB").getcolors(png.width * png.height))
                assert colors.get((31, 119, 180), 0) > 100
            assert vb.viewRange() == original_range
            assert window._frequency_axis.labelUnits == "THz"
        window.close()
        window.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
        app.processEvents()
        assert not shiboken6.isValid(window)
        del window, vb
        print(f"destroyed {iteration + 1}", flush=True)
    app.quit()
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
