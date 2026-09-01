"""
Clipboard to Print — protótipo
--------------------------------
Fica em segundo plano (ícone na bandeja do sistema). Você copia uma
mensagem/conversa do DeepSeek (ou de qualquer lugar) com Ctrl+C,
aperta o atalho global (padrão: Ctrl+Alt+P), e uma janela de preview
com o Markdown já formatado em HTML aparece. Você revisa e clica em
"Imprimir na HP" para mandar direto pra impressora configurada
(sem abrir nenhum diálogo do Windows), ou em "Escolher impressora..."
para usar o diálogo de impressão normal do Windows e escolher outra.

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
- A impressão automática usa QTextDocument + QPrinter do Qt,
  selecionando a impressora pelo nome (DEFAULT_PRINTER_NAME) — não
  depende de simular cliques na tela, então funciona igual rodando
  interativamente ou via Agendador de Tarefas.
"""

import os
import subprocess
import sys

import markdown
import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
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
    QMessageBox,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo

try:
    import keyboard  # atalho global (fora da janela do app)
    HAS_GLOBAL_HOTKEY = True
except ImportError:
    HAS_GLOBAL_HOTKEY = False

HOTKEY = "ctrl+alt+p"

WINDOW_READY_DELAY_MS = 250
WIDTH = 700
HEIGHT = 600

# Nome exato (ou o mais próximo disso) da impressora, como aparece em
# "Impressoras e scanners" do Windows. Ajuste aqui se o nome mudar
# (troca de driver, reinstalação, etc.) — não precisa mexer no resto
# do código.
DEFAULT_PRINTER_NAME = "HPE62BEC (HP Smart Tank 580-590 series)"


def find_installed_printer_name(preferred: str) -> str | None:
    """
    Procura, entre as impressoras instaladas no Windows, uma que
    corresponda ao nome preferido — tentando primeiro correspondência
    exata, depois ignorando maiúsculas/espaços, depois por substring.
    Isso torna a escolha da impressora resiliente a pequenas variações
    de nome entre máquinas/drivers, sem depender de reconhecer nada na
    tela (ao contrário do pyautogui).

    Retorna o nome exato como o Qt/Windows o conhece, ou None se
    nenhuma impressora parecida estiver instalada.
    """
    available = QPrinterInfo.availablePrinterNames()

    if preferred in available:
        return preferred

    preferred_norm = preferred.strip().lower()
    for name in available:
        if name.strip().lower() == preferred_norm:
            return name

    for name in available:
        if preferred_norm in name.strip().lower():
            return name

    return None

def get_base_dir() -> str:
    """
    Pasta "de referência" do programa.

    - Rodando como script normal (python imprimir.py): pasta do próprio
      arquivo .py.
    - Rodando como .exe gerado pelo PyInstaller (sys.frozen == True):
      pasta onde o .exe está, e NÃO a pasta temporária de extração
      (sys._MEIPASS) usada internamente pelo modo --onefile. Isso é
      importante porque a pasta "imagens/" e o arquivo de log devem
      ficar ao lado do .exe (editáveis pelo usuário), não escondidos
      dentro do executável.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


SCRIPT_DIR = get_base_dir()
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Flag de linha de comando usada para o PRÓPRIO executável se
# re-lançar apenas para rodar a rotina de clique (clicar_melhorado),
# como um processo separado — preservando o isolamento e o
# não-bloqueio do event loop do Qt que já existia antes, mas agora
# funcionando também quando tudo está empacotado num único .exe (não
# há mais um clicar_melhorado.py separado para apontar via
# sys.executable + caminho).
RUN_CLICAR_FLAG = "--run-clicar"

# Caminho deste próprio script/exe, usado para o relançamento.
# - Modo dev: THIS_ENTRYPOINT = imprimir.py (precisa passar o caminho
#   pro interpretador Python saber o que executar).
# - Modo congelado (.exe): sys.executable já É o programa todo; não
#   se passa nenhum caminho de script, só a flag.
THIS_ENTRYPOINT = os.path.abspath(__file__)

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
    
    window_ready = pyqtSignal()

    def __init__(self, html: str):
        super().__init__()
        self.setWindowTitle("Preview de impressão — Clipboard to Print")
        self.resize(WIDTH, HEIGHT)

        layout = QVBoxLayout(self)

        info = QLabel("Confira o conteúdo abaixo antes de imprimir:")
        layout.addWidget(info)

        self.text_edit = QTextEdit()
        self.text_edit.setHtml(html)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        button_row = QHBoxLayout()
        outra_impressora_btn = QPushButton("Escolher impressora...")
        outra_impressora_btn.clicked.connect(self.handle_print_with_dialog)
        print_btn = QPushButton("Imprimir na HP")
        print_btn.clicked.connect(self.handle_print_auto)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(outra_impressora_btn)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(print_btn)
        layout.addLayout(button_row)

        self._ready_signal_sent = False

    def showEvent(self, event):
        super().showEvent(event)
        
        if not self._ready_signal_sent:
            self._ready_signal_sent = True
            QTimer.singleShot(WINDOW_READY_DELAY_MS, self.window_ready.emit)

    def handle_print_auto(self):
        """
        Imprime direto na impressora configurada (DEFAULT_PRINTER_NAME),
        via QPrinter, sem abrir nenhum diálogo do Windows e sem precisar
        clicar em nada na tela. Isso resolve o problema de rodar via
        Agendador de Tarefas: a automação por imagem (pyautogui) depende
        de como o diálogo do Windows aparece na tela — o que muda
        conforme a sessão/contexto em que o processo foi iniciado. Selecionar
        a impressora por nome, pela API do Qt, não depende disso.
        """
        printer_name = find_installed_printer_name(DEFAULT_PRINTER_NAME)

        if printer_name is None:
            QMessageBox.warning(
                self,
                "Impressora não encontrada",
                f"Não encontrei nenhuma impressora instalada parecida com "
                f"\"{DEFAULT_PRINTER_NAME}\".\n\n"
                "Escolha manualmente na próxima janela.",
            )
            self.handle_print_with_dialog()
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(printer_name)
        self.text_edit.document().print(printer)
        self.close()

    def handle_print_with_dialog(self):
        """Abre o diálogo de impressão normal do Windows, para escolher outra impressora manualmente."""
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

        # Guarda referência ao processo lançado, para não ser coletado
        # pelo garbage collector enquanto ainda está rodando.
        self._clicar_process = None

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
        # Não conectamos mais window_ready a run_clicar_melhorado: a
        # impressão agora é feita diretamente pelo Qt (QPrinter,
        # selecionando a impressora pelo nome), sem precisar simular
        # cliques na tela. O método abaixo continua disponível caso
        # algum dia sirva para outra automação, mas não é mais chamado
        # automaticamente no fluxo de impressão.
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def run_clicar_melhorado(self):
        """
        Dispara a automação de clique depois que o preview já abriu.

        Antes isso era feito com `import clicar_melhorado` seguido de
        `clicar_melhorado.rotina_clicar()` na própria thread principal
        — como essa thread é a mesma que desenha e responde a eventos
        da interface Qt, a janela de preview ficava "congelada"
        (sem redraw, sem resposta a cliques) enquanto a rotina de
        clique estivesse executando.

        Agora, a rotina de clique roda como um PROCESSO separado via
        subprocess.Popen() — o próprio programa se relança consigo
        mesmo, passando a flag "--run-clicar". Isso:
          - não bloqueia o event loop do Qt (a chamada Popen() retorna
            na hora, o processo continua rodando em paralelo);
          - isola falhas: se a rotina de clique travar ou crashar,
            isso não derruba o app principal;
          - funciona igual rodando como script (`python imprimir.py`)
            ou já empacotado como um único .exe pelo PyInstaller —
            não depende mais de um arquivo clicar_melhorado.py solto
            ao lado, já que ele passa a ser importado como módulo;
          - tem a contrapartida de que trocar dados diretamente entre
            os dois processos (variáveis Python compartilhadas) não é
            mais possível — se precisar disso no futuro, dá pra usar
            argumentos de linha de comando, um arquivo temporário, ou
            stdin/stdout.
        """
        try:
            if getattr(sys, "frozen", False):
                # .exe empacotado: sys.executable já é o programa
                # inteiro, não se passa caminho de script nenhum.
                args = [sys.executable, RUN_CLICAR_FLAG]
            else:
                # Rodando via "python imprimir.py": precisa dizer ao
                # interpretador qual script executar.
                args = [sys.executable, THIS_ENTRYPOINT, RUN_CLICAR_FLAG]

            self._clicar_process = subprocess.Popen(args, cwd=SCRIPT_DIR)
        except OSError as e:
            # Ex: permissão negada, interpretador não encontrado, etc.
            self.tray.showMessage(
                "Clipboard to Print",
                f"Erro ao iniciar clicar_melhorado.py: {e}",
                QSystemTrayIcon.MessageIcon.Critical,
            )

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    if RUN_CLICAR_FLAG in sys.argv:
        # Este mesmo programa foi relançado (como subprocesso) só para
        # executar a automação de clique, isolada em outro processo —
        # ver a explicação em run_clicar_melhorado() acima. Roda a
        # rotina e encerra, sem nunca abrir a janela/tray do Qt.
        import clicar_melhorado
        clicar_melhorado.rotina_clicar()
        sys.exit(0)

    app = ClipboardToPrintApp()
    app.run()