import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, QLockFile, QSettings, QStandardPaths, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QPlainTextEdit, QProgressBar,
    QPushButton, QToolButton, QVBoxLayout, QWidget)

from engine import Cancelled, HOME, Runner, VERSION, tool, update

STRINGS = {
    "links": ("Cole um ou mais links", "Paste one or more links", "Pega uno o más enlaces"),
    "paste": ("Colar", "Paste", "Pegar"), "inspect": ("Analisar", "Analyze", "Analizar"),
    "single": ("Somente o item atual", "Current item only", "Solo el elemento actual"),
    "whole": ("Playlist inteira", "Entire playlist", "Lista completa"),
    "legacy": ("Aparelhos antigos · 720p", "Older devices · 720p", "Equipos antiguos · 720p"),
    "best": ("Melhor qualidade disponível", "Best available quality", "Mejor calidad disponible"),
    "cap": ("Até", "Up to", "Hasta"), "folder": ("Pasta de destino", "Destination folder", "Carpeta de destino"),
    "download": ("Baixar", "Download", "Descargar"), "cancel": ("Cancelar", "Cancel", "Cancelar"),
    "retry": ("Repetir falhas", "Retry failed", "Reintentar fallidos"),
    "history": ("Histórico", "History", "Historial"), "diag": ("Copiar diagnóstico", "Copy diagnostic", "Copiar diagnóstico"),
    "update": ("Atualizar yt-dlp", "Update yt-dlp", "Actualizar yt-dlp"),
    "last": ("Última verificação", "Last checked", "Última comprobación"),
    "theme": ("Tema escuro", "Dark theme", "Tema oscuro"),
    "idle": ("Pronto", "Ready", "Listo"), "analyze": ("Analisando", "Analyzing", "Analizando"),
    "video": ("Baixando vídeo", "Downloading video", "Descargando vídeo"),
    "audio": ("Baixando áudio", "Downloading audio", "Descargando audio"),
    "merge": ("Juntando vídeo e áudio", "Merging video and audio", "Uniendo vídeo y audio"),
    "mp4": ("Convertendo para MP4", "Converting to MP4", "Convirtiendo a MP4"),
    "mp3": ("Convertendo para MP3", "Converting to MP3", "Convirtiendo a MP3"),
    "verify": ("Verificando compatibilidade", "Checking compatibility", "Verificando compatibilidad"),
    "done": ("Concluído", "Completed", "Completado"), "fail": ("Falha", "Failed", "Error"),
    "stop": ("Cancelado", "Cancelled", "Cancelado"),
    "invalid_url": ("Link inválido", "Invalid link", "Enlace no válido"),
    "unavailable": ("Item indisponível", "Item unavailable", "Elemento no disponible"),
    "validation": ("Falha na validação do arquivo", "File validation failed", "Error al validar el archivo"),
    "exists": ("Arquivo já existente", "File already exists", "El archivo ya existe"),
    "429": ("HTTP 429 · limite atingido", "HTTP 429 · rate limit reached", "HTTP 429 · límite alcanzado"),
    "403": ("HTTP 403 · acesso negado", "HTTP 403 · access denied", "HTTP 403 · acceso denegado"),
    "space": ("Espaço insuficiente", "Insufficient disk space", "Espacio insuficiente"),
    "network": ("Problema de conexão", "Connection problem", "Problema de conexión"),
    "missing": ("Componente indisponível", "Component unavailable", "Componente no disponible"),
    "convert": ("Falha na conversão", "Conversion failed", "Error de conversión"),
    "stale": ("Verifique a atualização do yt-dlp", "Check for a yt-dlp update", "Comprueba la actualización de yt-dlp"),
}


def error(exc):
    message = str(exc).lower()
    if isinstance(exc, FileExistsError):
        return "exists"
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if message in STRINGS:
        return message
    for token, code in (("429","429"), ("403","403"), ("space","space"), ("connection","network"),
                        ("timed out","network"), ("unavailable","unavailable"), ("ffmpeg","convert"),
                        ("update","stale")):
        if token in message:
            return code
    return "fail"


class Job(QThread):
    event = Signal(str, object)

    def __init__(self, action, urls, whole, dest, ext, cap, retry):
        super().__init__()
        self.action, self.urls, self.whole = action, urls, whole
        self.options = Path(dest), ext, cap
        self.retry = retry
        self.runner = Runner(lambda phase, detail: self.event.emit("status", (phase, detail)))

    def run(self):
        failures = []
        try:
            if self.action in ("versions","update"):
                if self.action == "update":
                    self.event.emit("updated", update(self.runner))
                versions = []
                for name, arg in (("yt-dlp","--version"),("ffmpeg","-version")):
                    try:
                        versions.append(self.runner.run([tool(name),arg]).splitlines()[0].split(" Copyright")[0])
                    except Exception as exc:
                        versions.append(str(exc))
                self.event.emit("versions", versions)
                return
            items = list(self.retry)
            for url in self.urls:
                self.runner.notify("analyze", url)
                try:
                    found = self.runner.inspect(url, self.whole or self.action == "inspect")
                    if not found:
                        raise ValueError("unavailable")
                    self.event.emit("preview", (found[0][2] or found[0][1], len(found)))
                    thumb = found[0][-1]
                    if thumb and thumb.startswith("https://"):
                        try:
                            with urllib.request.urlopen(thumb, timeout=5) as response:
                                self.event.emit("image", response.read(2_000_000))
                        except OSError:
                            pass
                    items.extend(found)
                except Cancelled:
                    raise
                except Exception as exc:
                    self.event.emit("error", (error(exc), url, str(exc)))
                    if error(exc) == "429":
                        return
            if self.action == "inspect":
                return
            for n, item in enumerate(items, 1):
                self.event.emit("item", (n, len(items), item[1]))
                try:
                    path = self.runner.process(item, *self.options)
                    self.event.emit("complete", str(path))
                except Cancelled:
                    failures.extend(items[n-1:])
                    raise
                except Exception as exc:
                    code = error(exc)
                    self.event.emit("error", (code, item[1], str(exc)))
                    if code != "exists":
                        failures.append(item)
                    if code == "429":
                        failures.extend(items[n:])
                        break
        except Cancelled:
            self.runner.notify("stop", "")
        except Exception as exc:
            self.event.emit("error", (error(exc), "", str(exc)))
        finally:
            self.event.emit("failures", failures)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ytdlp-G Lite")
        self.resize(740, 700)
        self.settings = QSettings("Ytdlp-G Lite", "Lite")
        default = {"pt":0,"es":2}.get(QLocale.system().name()[:2],1)
        self.lang = int(self.settings.value("language", default))
        self.dark = self.settings.value("dark", False, type=bool)
        self.failed, self.diagnostic, self.job = [], "", None
        self.root = QWidget()
        self.setCentralWidget(self.root)
        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(28,22,28,22)
        layout.setSpacing(10)
        self.labels = {}
        def row(parent):
            r = QHBoxLayout()
            parent.addLayout(r)
            return r
        def button(key, callback, parent):
            b = QPushButton()
            self.labels[key] = b
            b.clicked.connect(callback)
            parent.addWidget(b)
            return b
        header = row(layout)
        title = QLabel("Ytdlp-G Lite")
        title.setObjectName("brand")
        header.addWidget(title)
        header.addStretch()
        self.menu = QToolButton()
        self.menu.setText("⚙")
        self.menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self.menu)
        card = QFrame()
        card.setObjectName("card")
        layout.addWidget(card)
        body = QVBoxLayout(card)
        body.setContentsMargins(18,16,18,16)
        self.links = QPlainTextEdit()
        self.links.setMaximumHeight(76)
        body.addWidget(self.links)
        actions = row(body)
        self.thumb = QLabel()
        actions.addWidget(self.thumb)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        actions.addWidget(self.preview, 1)
        button("paste", lambda: self.links.insertPlainText(QApplication.clipboard().text()+"\n"), actions)
        button("inspect", lambda: self.start("inspect"), actions)
        choices = row(body)
        self.ext, self.quality, self.scope = QComboBox(), QComboBox(), QComboBox()
        self.ext.addItems(["MP4", "MP3"])
        for combo in (self.ext,self.quality,self.scope):
            choices.addWidget(combo)
        self.ext.currentIndexChanged.connect(lambda i: self.quality.setVisible(i == 0))
        destrow = row(body)
        self.dest = QLineEdit(self.settings.value("destination", QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)))
        destrow.addWidget(self.dest)
        button("folder", self.browse, destrow)
        controls = row(body)
        self.download = button("download", lambda: self.start("download"), controls)
        self.download.setObjectName("primary")
        self.cancel = button("cancel", lambda: self.job.runner.cancel.set(), controls)
        self.cancel.hide()
        self.retry = button("retry", lambda: self.start("retry"), controls)
        self.retry.hide()
        self.current, self.status, self.bar = QLabel(), QLabel(), QProgressBar()
        self.bar.setValue(0)
        for widget in (self.current,self.bar,self.status):
            layout.addWidget(widget)
        self.labels["history"] = QLabel()
        layout.addWidget(self.labels["history"])
        self.history = QListWidget()
        layout.addWidget(self.history,1)
        self.history.addItems(json.loads(self.settings.value("history","[]")))
        footer = row(layout)
        button("update", lambda: self.start("update"), footer)
        footer.addStretch()
        button("diag", lambda: QApplication.clipboard().setText(self.diagnostic),footer)
        self.versions = QLabel(VERSION)
        self.versions.setWordWrap(True)
        layout.addWidget(self.versions)
        self.populate()
        self.start("versions")

    def trkey(self,key):
        return STRINGS[key][self.lang]

    def populate(self):
        for k,b in self.labels.items():
            b.setText(self.trkey(k))
        self.links.setPlaceholderText(self.trkey("links"))
        self.status.setText(self.trkey("idle"))
        for combo,names in ((self.scope,[self.trkey("single"),self.trkey("whole")]),
            (self.quality,[self.trkey("best")] + [f"{self.trkey('cap')} {x}p" for x in (2160,1440,1080,720,480,360)] + [self.trkey("legacy")])):
            index = combo.currentIndex()
            combo.clear()
            combo.addItems(names)
            combo.setCurrentIndex(max(index,0))
        menu = QMenu(self)
        for i,name in enumerate(("Português brasileiro","English","Español")):
            menu.addAction(name, lambda checked=False, i=i: self.language(i))
        menu.addSeparator()
        theme = menu.addAction(self.trkey("theme"),self.theme)
        theme.setCheckable(True)
        theme.setChecked(self.dark)
        self.menu.setMenu(menu)
        bg, surface, fg, border, accent = (("#171c23","#222a34","#edf1f5","#424d59","#71dfbb") if self.dark
            else ("#f0f4f3","#ffffff","#192f2c","#cbd8d4","#98e5c8"))
        self.setStyleSheet(f"""QWidget {{font: 10pt 'Segoe UI'; color:{fg};}}
            QMainWindow,QWidget#central {{background:{bg};}} QFrame#card,QListWidget,QMenu {{background:{surface}; border:1px solid {border}; border-radius:12px;}}
            QPlainTextEdit,QLineEdit,QComboBox,QPushButton,QToolButton {{background:{surface};border:1px solid {border}; border-radius:7px;padding:7px;}}
            QPushButton:hover,QToolButton:hover {{border-color:#42aa8d;}} QPushButton#primary {{background:{accent};color:#15352d;font-weight:600;}}
            QLabel#brand {{font-size:23pt;font-weight:650;}} QProgressBar {{background:{surface};border:1px solid {border};border-radius:5px;text-align:center;}}
            QProgressBar::chunk {{background:#48ac91;}} QListWidget::item {{padding:5px;}}""")

    def language(self,i):
        self.lang = i
        self.settings.setValue("language",i)
        self.populate()

    def theme(self):
        self.dark = not self.dark
        self.settings.setValue("dark",self.dark)
        self.populate()

    def browse(self):
        path = QFileDialog.getExistingDirectory(self,self.trkey("folder"),self.dest.text())
        if path:
            self.dest.setText(path)

    def start(self,action):
        if self.job and self.job.isRunning():
            return
        urls = self.links.toPlainText().split() if action in ("inspect","download") else []
        if action in ("inspect","download") and not urls:
            self.status.setText(self.trkey("invalid_url"))
            return
        self.settings.setValue("destination",self.dest.text())
        self.job = Job(action,urls,bool(self.scope.currentIndex()),self.dest.text(),self.ext.currentText().lower(),
                       [0,2160,1440,1080,720,480,360,-1][self.quality.currentIndex()],self.failed if action=="retry" else [])
        self.job.event.connect(self.event_received)
        self.job.finished.connect(lambda: self.busy(False))
        self.busy(True)
        self.job.start()

    def busy(self,value):
        
        for widget in (self.download,self.retry,self.links,self.ext,self.quality,self.scope,self.dest,
                       self.menu,*(self.labels[k] for k in ("paste","inspect","folder","update"))):
            widget.setEnabled(not value)
        self.cancel.setVisible(value and self.job.action not in ("versions","update"))
        if not value:
            self.bar.setRange(0,100)

    def event_received(self,key,data):
        if key == "preview":
            self.preview.setText(f"{data[0]} · {data[1]}")
        elif key == "image":
            pix = QPixmap()
            if pix.loadFromData(data):
                self.thumb.setPixmap(pix.scaled(80,48,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        elif key == "status":
            self.status.setText(self.trkey(data[0])+"  "+data[1])
            match = re.match(r"([\d.]+)%",data[1])
            self.bar.setRange(0,100 if match else 0)
            if match:
                self.bar.setValue(int(float(match[1])))
        elif key == "item":
            self.current.setText(f"{data[0]} / {data[1]}   {data[2]}")
        elif key in ("error","complete"):
            if key == "error":
                code,name,self.diagnostic = data
                message = self.trkey(code)+" · "+name
                if code in ("missing","fail"):
                    message += " · "+self.diagnostic[-180:]
            else:
                message = self.trkey("done")+" · "+data
                self.bar.setRange(0,100)
                self.bar.setValue(100)
            self.status.setText(message)
            self.history.insertItem(0,message)
            self.settings.setValue("history",json.dumps([self.history.item(i).text() for i in range(min(100,self.history.count()))]))
        elif key == "failures" and self.job.action in ("retry","download"):
            self.failed = data
            self.retry.setVisible(bool(data))
        elif key == "updated":
            self.settings.setValue("checked",datetime.now().strftime("%Y-%m-%d %H:%M"))
            self.status.setText(self.trkey("done")+" · yt-dlp "+data)
        elif key == "versions":
            self.versions.setText(f"Lite {VERSION}   ·   yt-dlp {data[0]}   ·   {data[1]}\n{self.trkey('last')}   {self.settings.value('checked','—')}")

    def closeEvent(self,event):
        if self.job and self.job.isRunning():
            self.job.runner.cancel.set()
            self.job.finished.connect(self.close)
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    lockdir = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "Ytdlp-G-Lite"
    lockdir.mkdir(parents=True,exist_ok=True)
    lock = QLockFile(str(lockdir/"active.lock"))
    if not lock.tryLock():
        return
    window = Window()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
