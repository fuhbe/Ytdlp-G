"""Stable-key translation catalogs with live Qt bindings and Portuguese fallback."""

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QObject, QTranslator, Signal

ROOT = Path(__file__).parent
CATALOGS = {
    language: json.loads((ROOT / f"{language}.json").read_text("utf-8"))
    for language in ("pt-BR", "en", "es")
}


def translate(language, key, **values):
    return CATALOGS.get(language, {}).get(key, CATALOGS["pt-BR"].get(key, key)).format(**values)


class Translator(QObject):
    changed = Signal()

    def __init__(self, language="pt-BR"):
        super().__init__()
        self.language = language
        self.bindings = []
        self.qt = None
        self.install_qt_translation()

    def install_qt_translation(self):
        app = QCoreApplication.instance()
        if not app:
            return
        if self.qt:
            app.removeTranslator(self.qt)
        self.qt = QTranslator(self)
        locale_name = self.language.replace("-", "_")
        QLocale.setDefault(QLocale(locale_name))
        if self.language != "en":
            name = "qtbase_" + locale_name
            loaded = self.qt.load(
                name, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            )
            if not loaded:
                loaded = self.qt.load(name, str(ROOT.parent / "resources" / "translations"))
            if loaded:
                app.installTranslator(self.qt)

    def __call__(self, key, **values):
        return translate(self.language, key, **values)

    def bind(self, setter, key):
        self.bindings.append((setter, key))
        setter(self(key))

    def set_language(self, language):
        self.language = language if language in CATALOGS else "pt-BR"
        self.install_qt_translation()
        for setter, key in self.bindings:
            setter(self(key))
        self.changed.emit()
