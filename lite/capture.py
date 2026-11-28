import os
import sys
from pathlib import Path

import engine
from app import Window
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

if os.getenv("LITE_TEST_TOOLS"):
    engine.TOOLS = Path(os.environ["LITE_TEST_TOOLS"])
app = QApplication([])
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(
    QSettings.IniFormat, QSettings.UserScope, str(Path(sys.argv[1]).resolve() / ".settings")
)
window = Window()
window.language(0)
window.show()
window.job.wait()
app.processEvents()
for dark in (False, True):
    window.dark = dark
    window.populate()
    app.processEvents()
    assert window.grab().save(str(Path(sys.argv[1]) / ("dark.png" if dark else "light.png")))
window.close()
