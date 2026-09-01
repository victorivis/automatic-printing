"""
Clipboard to Print — protótipo
--------------------------------
Fica em segundo plano (ícone na bandeja do sistema). Você copia uma
mensagem/conversa do DeepSeek (ou de qualquer lugar) com Ctrl+C,
aperta o atalho global (padrão: Ctrl+Alt+P), e uma janela de preview
com o Markdown já formatado em HTML aparece. Você revisa e manda
imprimir na impressora que quiser (inclusive a HP), usando o diálogo
de impressão normal do Windows.

Instalação:
    pip install PyQt6 pyperclip keyboard markdown

Execução:
    python clipboard_to_print.py

Observações importantes:
- No Windows, a biblioteca "keyboard" às vezes exige executar o
  terminal/script como Administrador para capturar o atalho global.
- No Linux, "keyboard" geralmente precisa rodar como root (acesso a
  /dev/input). Se isso for um problema, dá pra trocar por um atalho
  registrado só dentro da própria janela do Qt (sem ser "global").
- A impressão usa QTextDocument + QPrintDialog do Qt: ele lista
  todas as impressoras instaladas no sistema, incluindo a HP — não é
  necessário integrar com nenhum software específico da HP.
"""

import sys

import markdown
import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextDocument, QIcon, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QSystemTrayIcon,
    QMenu,
    QStyle,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter

try:
    import keyboard  # atalho global (fora da janela do app)
    HAS_GLOBAL_HOTKEY = True
except ImportError:
    HAS_GLOBAL_HOTKEY = False

HOTKEY = "ctrl+alt+p"

# CSS simples para a conversa ficar legível tanto na tela quanto impressa
PRINT_CSS = """
<style>
    body { font-family: Segoe UI, Arial, sans-serif; font-size: 12pt; line-height: 1.4; }
    h1, h2, h3 { color: #1a1a1a; }
    code { background-color: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-family: Consolas, monospace; }
    pre code { display: block; padding: 8px; white-space: pre-wrap; }
    blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 10px; color: #555; }
    table { border-collapse: collapse; }
    td, th { border: 1px solid #999; padding: 4px 8px; }
</style>
"""


def markdown_to_html(text: str) -> str:
    """Converte o texto do clipboard (assumido como Markdown) em HTML pronto para exibir/imprimir."""
    body_html = markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "nl2br"],
    )
    return f"<html><head>{PRINT_CSS}</head><body>{body_html}</body></html>"


class PreviewDialog(QDialog):
    """Janela de preview: mostra o Markdown já formatado antes de imprimir."""

    def __init__(self, html: str):
        super().__init__()
        self.setWindowTitle("Preview de impressão — Clipboard to Print")
        self.resize(700, 800)

        layout = QVBoxLayout(self)

        info = QLabel("Confira o conteúdo abaixo antes de imprimir:")
        layout.addWidget(info)

        self.text_edit = QTextEdit()
        self.text_edit.setHtml(html)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        button_row = QHBoxLayout()
        print_btn = QPushButton("Imprimir")
        print_btn.clicked.connect(self.handle_print)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(cancel_btn)
        button_row.addWidget(print_btn)
        layout.addLayout(button_row)

    def handle_print(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.text_edit.document().print(printer)
        self.close()


class HotkeyBridge(QObject):
    """
    A lib 'keyboard' dispara o callback do atalho numa thread separada
    (a thread de captura de teclado do sistema). O Qt não permite criar
    ou manipular widgets fora da thread principal (dá o erro
    'Cannot create children for a parent that is in a different thread').

    Solução: o callback da thread do 'keyboard' só emite este sinal.
    Como o receptor (a função conectada a ele) vive na thread principal,
    o Qt automaticamente enfileira a chamada para rodar lá — isso é
    seguro entre threads (padrão AutoConnection do Qt).
    """
    triggered = pyqtSignal()


class ClipboardToPrintApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.triggered.connect(self.trigger_from_clipboard)

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.tray.setToolTip("Clipboard to Print")

        menu = QMenu()
        print_action = QAction(f"Imprimir clipboard agora ({HOTKEY})")
        print_action.triggered.connect(self.trigger_from_clipboard)
        menu.addAction(print_action)

        quit_action = QAction("Sair")
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

        if HAS_GLOBAL_HOTKEY:
            # Importante: o callback do keyboard roda em outra thread,
            # então ele só pode emitir o sinal — nunca chamar
            # self.trigger_from_clipboard diretamente daqui.
            keyboard.add_hotkey(HOTKEY, self.hotkey_bridge.triggered.emit)
        else:
            self.tray.showMessage(
                "Clipboard to Print",
                "Biblioteca 'keyboard' não encontrada — use o menu da bandeja para imprimir.",
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def trigger_from_clipboard(self):
        text = pyperclip.paste()
        if not text or not text.strip():
            self.tray.showMessage(
                "Clipboard to Print",
                "Área de transferência vazia — copie uma mensagem primeiro.",
                QSystemTrayIcon.MessageIcon.Information,
            )
            return

        html = markdown_to_html(text)
        # Guarda referência para o dialog não ser coletado pelo garbage collector
        self.dialog = PreviewDialog(html)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    app = ClipboardToPrintApp()
    app.run()