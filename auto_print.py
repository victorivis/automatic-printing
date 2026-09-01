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

Também dá pra imprimir um PDF: pelo menu da bandeja, "Imprimir PDF
selecionado no Explorer" pega o arquivo .pdf selecionado na janela do
Explorer em primeiro plano, ou "Escolher PDF para imprimir..." abre um
seletor de arquivos. Os dois abrem a mesma janela de confirmação, com
as mesmas opções de impressão simples ou frente e verso.

Instalação:
    pip install PyQt6 pyperclip keyboard markdown pywin32

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
- "Imprimir PDF selecionado no Explorer" depende de "pywin32"
  (win32com/win32gui) para conversar com o Explorer via COM. Sem essa
  lib instalada, essa opção específica simplesmente não funciona —
  "Escolher PDF para imprimir..." continua funcionando normalmente.
"""

import os
import subprocess
import sys

import markdown
import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QSizeF, QSize, QPointF, Qt
from PyQt6.QtGui import QTextDocument, QIcon, QAction, QPainter
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
    QFileDialog,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtPdf import QPdfDocument

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

# Impressão frente e verso manual: depois de virar a pilha de papel já
# impressa e recolocar na bandeja, a ordem física em que as folhas vão
# ser alimentadas de volta depende do modelo/bandeja da impressora —
# não tem como o software adivinhar isso com certeza. O padrão mais
# comum (pilha sai com a última página impressa por cima; ao virar a
# pilha inteira como um bloco e recolocar, a impressora volta a
# alimentar a partir do que antes estava embaixo) é imprimir as
# páginas pares em ordem DECRESCENTE na segunda passada. Se, ao testar
# com um documento curto (4 páginas, por exemplo), os versos saírem
# fora de ordem ou de cabeça para baixo, troque este valor para False
# e teste de novo.
EVEN_PAGES_REVERSED = True


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


def compute_total_pages(document: QTextDocument, printer: QPrinter) -> int:
    """
    Descobre quantas páginas o documento vai ocupar ao ser impresso
    nesta impressora — precisamos saber isso de antemão para montar as
    listas de páginas ímpares/pares. Isso ajusta o tamanho de página
    do documento para bater com a área imprimível da impressora (é o
    que document.print(printer) faz por baixo dos panos automaticamente
    numa impressão normal).
    """
    page_size = QSizeF(printer.pageRect(QPrinter.Unit.DevicePixel).size())
    document.setPageSize(page_size)
    return document.pageCount()


def print_pages(document: QTextDocument, printer: QPrinter, page_numbers: list) -> None:
    """
    Imprime apenas as páginas (numeração começando em 1) presentes em
    `page_numbers`, na ordem em que aparecem na lista.

    QTextDocument.print() sempre imprime o documento inteiro de uma
    vez; para selecionar só algumas páginas usamos o mesmo mecanismo
    do diálogo de impressão do Windows (printRange + fromPage/toPage),
    chamando print() uma vez por página. Cada chamada gera um "job" de
    impressão próprio, mas fisicamente as folhas saem uma atrás da
    outra, na ordem em que foram enviadas.
    """
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    for page_num in page_numbers:
        printer.setFromTo(page_num, page_num)
        document.print(printer)


def print_pdf_pages(pdf_doc: QPdfDocument, printer: QPrinter, page_numbers: list) -> None:
    """
    Renderiza e imprime as páginas de um PDF (numeração começando em
    1) presentes em `page_numbers`, na ordem dada, dentro de um único
    job de impressão (usando printer.newPage() entre uma página e
    outra).

    Ao contrário de QTextDocument, QPdfDocument não tem um método
    print() pronto — cada página é renderizada como imagem (na
    resolução da impressora, pra não perder qualidade) e desenhada
    centralizada na área imprimível.
    """
    painter = QPainter(printer)
    try:
        target_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        dpi = printer.resolution()

        for i, page_num in enumerate(page_numbers):
            if i > 0:
                printer.newPage()

            page_index = page_num - 1
            page_points = pdf_doc.pagePointSize(page_index)  # tamanho em pontos (1/72")
            render_size = QSize(
                round(page_points.width() / 72.0 * dpi),
                round(page_points.height() / 72.0 * dpi),
            )
            image = pdf_doc.render(page_index, render_size)

            scaled = image.scaled(
                target_rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = target_rect.x() + (target_rect.width() - scaled.width()) / 2
            y = target_rect.y() + (target_rect.height() - scaled.height()) / 2
            painter.drawImage(QPointF(x, y), scaled)
    finally:
        painter.end()


def get_selected_pdf_from_explorer():
    """
    Tenta descobrir o caminho de um arquivo .pdf atualmente selecionado
    na janela do Windows Explorer que estiver em primeiro plano.

    Usa automação COM ("Shell.Application") para listar as janelas do
    Explorer abertas, casa a que está em primeiro plano pelo HWND, e lê
    os itens selecionados nela. Retorna None se: pywin32 não estiver
    instalado, não houver Explorer em primeiro plano, nada estiver
    selecionado, ou o item selecionado não for um .pdf.
    """
    try:
        import win32com.client
        import win32gui
    except ImportError:
        return None

    try:
        foreground_hwnd = win32gui.GetForegroundWindow()
        shell = win32com.client.Dispatch("Shell.Application")

        for window in shell.Windows():
            try:
                if window.HWND != foreground_hwnd:
                    continue
                for item in window.Document.SelectedItems():
                    path = item.Path
                    if path and path.lower().endswith(".pdf"):
                        return path
            except Exception:
                continue
    except Exception:
        return None

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
        duplex_btn = QPushButton("Imprimir frente e verso")
        duplex_btn.clicked.connect(self.handle_print_duplex)
        print_btn = QPushButton("Imprimir na HP")
        print_btn.clicked.connect(self.handle_print_auto)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(outra_impressora_btn)
        button_row.addWidget(duplex_btn)
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

    def handle_print_duplex(self):
        """
        Impressão frente e verso manual: a HP Smart Tank 580-590 não
        tem duplex automático. Imprime primeiro as páginas ímpares,
        pede pra virar a pilha de papel e recolocar na bandeja, e só
        então imprime as páginas pares.
        """
        printer_name = find_installed_printer_name(DEFAULT_PRINTER_NAME)
        if printer_name is None:
            QMessageBox.warning(
                self,
                "Impressora não encontrada",
                f"Não encontrei nenhuma impressora instalada parecida com "
                f"\"{DEFAULT_PRINTER_NAME}\".\n\n"
                "Impressão frente e verso cancelada.",
            )
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(printer_name)

        document = self.text_edit.document()
        total_pages = compute_total_pages(document, printer)

        odd_pages = list(range(1, total_pages + 1, 2))
        even_pages = list(range(2, total_pages + 1, 2))

        if not even_pages:
            # Documento com 1 página só — não tem verso pra imprimir.
            print_pages(document, printer, odd_pages)
            self.close()
            return

        if EVEN_PAGES_REVERSED:
            even_pages = list(reversed(even_pages))

        print_pages(document, printer, odd_pages)

        resposta = QMessageBox.question(
            self,
            "Vire as páginas",
            f"As {len(odd_pages)} página(s) de frente foram enviadas "
            "para a impressora.\n\n"
            "Pegue a pilha impressa na bandeja de saída, vire-a inteira "
            "(sem embaralhar a ordem das folhas) e recoloque na "
            "bandeja de entrada.\n\n"
            "Quando estiver pronto, clique em \"OK\" para imprimir o verso.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )

        if resposta == QMessageBox.StandardButton.Ok:
            print_pages(document, printer, even_pages)

        self.close()


class PdfPrintDialog(QDialog):
    """
    Janela de confirmação para imprimir um arquivo PDF (selecionado no
    Explorer ou escolhido manualmente) — mesmas opções de impressão da
    PreviewDialog (impressora padrão, escolher outra, frente e verso),
    mas operando sobre um QPdfDocument em vez de um QTextDocument com
    HTML do clipboard.
    """

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.setWindowTitle("Imprimir PDF — Clipboard to Print")
        self.resize(420, 180)

        self.pdf_doc = QPdfDocument(None)
        self.pdf_doc.load(pdf_path)

        layout = QVBoxLayout(self)

        nome_arquivo = os.path.basename(pdf_path)
        if self.pdf_doc.status() == QPdfDocument.Status.Ready:
            total_pages = self.pdf_doc.pageCount()
            info_text = f"Arquivo: {nome_arquivo}\nPáginas: {total_pages}"
        else:
            total_pages = 0
            info_text = (
                f"Arquivo: {nome_arquivo}\n"
                "⚠️ Não consegui abrir este PDF (arquivo corrompido, "
                "protegido por senha, ou caminho inválido)."
            )
        self._total_pages = total_pages

        info = QLabel(info_text)
        layout.addWidget(info)

        abrir_btn = QPushButton("Abrir PDF para conferir")
        abrir_btn.clicked.connect(self.abrir_pdf_externamente)
        layout.addWidget(abrir_btn)

        button_row = QHBoxLayout()
        outra_impressora_btn = QPushButton("Escolher impressora...")
        outra_impressora_btn.clicked.connect(self.handle_print_with_dialog)
        duplex_btn = QPushButton("Imprimir frente e verso")
        duplex_btn.clicked.connect(self.handle_print_duplex)
        print_btn = QPushButton("Imprimir na HP (um lado)")
        print_btn.clicked.connect(self.handle_print_auto)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(outra_impressora_btn)
        button_row.addWidget(duplex_btn)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(print_btn)
        layout.addLayout(button_row)

        if total_pages == 0:
            outra_impressora_btn.setEnabled(False)
            duplex_btn.setEnabled(False)
            print_btn.setEnabled(False)

    def abrir_pdf_externamente(self):
        try:
            os.startfile(self.pdf_path)
        except Exception as e:
            QMessageBox.warning(self, "Erro ao abrir PDF", str(e))

    def handle_print_auto(self):
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
        print_pdf_pages(self.pdf_doc, printer, list(range(1, self._total_pages + 1)))
        self.close()

    def handle_print_with_dialog(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print_pdf_pages(self.pdf_doc, printer, list(range(1, self._total_pages + 1)))
        self.close()

    def handle_print_duplex(self):
        printer_name = find_installed_printer_name(DEFAULT_PRINTER_NAME)
        if printer_name is None:
            QMessageBox.warning(
                self,
                "Impressora não encontrada",
                f"Não encontrei nenhuma impressora instalada parecida com "
                f"\"{DEFAULT_PRINTER_NAME}\".\n\n"
                "Impressão frente e verso cancelada.",
            )
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(printer_name)

        odd_pages = list(range(1, self._total_pages + 1, 2))
        even_pages = list(range(2, self._total_pages + 1, 2))

        if not even_pages:
            print_pdf_pages(self.pdf_doc, printer, odd_pages)
            self.close()
            return

        if EVEN_PAGES_REVERSED:
            even_pages = list(reversed(even_pages))

        print_pdf_pages(self.pdf_doc, printer, odd_pages)

        resposta = QMessageBox.question(
            self,
            "Vire as páginas",
            f"As {len(odd_pages)} página(s) de frente foram enviadas "
            "para a impressora.\n\n"
            "Pegue a pilha impressa na bandeja de saída, vire-a inteira "
            "(sem embaralhar a ordem das folhas) e recoloque na "
            "bandeja de entrada.\n\n"
            "Quando estiver pronto, clique em \"OK\" para imprimir o verso.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )

        if resposta == QMessageBox.StandardButton.Ok:
            print_pdf_pages(self.pdf_doc, printer, even_pages)

        self.close()
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

        pdf_explorer_action = QAction("Imprimir PDF selecionado no Explorer")
        pdf_explorer_action.triggered.connect(self.trigger_pdf_from_explorer)
        menu.addAction(pdf_explorer_action)

        pdf_browse_action = QAction("Escolher PDF para imprimir...")
        pdf_browse_action.triggered.connect(self.trigger_pdf_from_dialog)
        menu.addAction(pdf_browse_action)

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

    def trigger_pdf_from_explorer(self):
        """Pega o .pdf selecionado na janela do Explorer em primeiro plano e abre a janela de impressão."""
        pdf_path = get_selected_pdf_from_explorer()
        if not pdf_path:
            self.tray.showMessage(
                "Clipboard to Print",
                "Não consegui identificar um PDF selecionado no Explorer. "
                "Selecione um arquivo .pdf numa janela do Explorer e tente de "
                "novo, ou use \"Escolher PDF para imprimir...\".",
                QSystemTrayIcon.MessageIcon.Information,
            )
            return
        self.open_pdf_print_dialog(pdf_path)

    def trigger_pdf_from_dialog(self):
        """Abre um seletor de arquivos para escolher qual PDF imprimir."""
        pdf_path, _ = QFileDialog.getOpenFileName(
            None, "Escolher PDF para imprimir", "", "Arquivos PDF (*.pdf)"
        )
        if not pdf_path:
            return  # usuário cancelou o seletor
        self.open_pdf_print_dialog(pdf_path)

    def open_pdf_print_dialog(self, pdf_path: str):
        # Guarda referência para o dialog não ser coletado pelo garbage collector
        self.pdf_dialog = PdfPrintDialog(pdf_path)
        self.pdf_dialog.show()
        self.pdf_dialog.raise_()
        self.pdf_dialog.activateWindow()

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