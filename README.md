# Dependências

```bash
pip install PyQt6 pyperclip keyboard markdown pyautogui opencv-python pyscreeze pillow pywin32
```

- `pywin32` é usado só pela opção "Imprimir PDF selecionado no Explorer" (lê a seleção do
  Windows Explorer via COM). Sem essa lib, essa opção específica fica indisponível, mas o
  resto do programa (clipboard, "Escolher PDF para imprimir...", frente e verso) continua
  funcionando normalmente.
- `QtPdf` (usado para renderizar/imprimir PDFs) já vem embutido no pacote `PyQt6` — não
  precisa instalar nada além disso.