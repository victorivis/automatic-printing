import pyautogui
import time
import os
from typing import Union, Dict

# ==================== CONFIGURAÇÕES GLOBAIS ====================
pyautogui.PAUSE = 0.3
pyautogui.FAILSAFE = True

INIT_TIME = 5
ACTION_PAUSE = 3
CLICK_PAUSE = 0.4
MOUSE_MOVE_TIME = 0.25
CONFIDENCE = 0.8
DEBUG = True

# ==================== DEFINIÇÃO DAS AÇÕES ====================
# Cada ação pode ser:
#   - Uma string: apenas o nome da imagem (clique central padrão)
#   - Um dicionário com os seguintes campos (todos opcionais, exceto 'nome'):
#       * nome         : (obrigatório) nome do arquivo da imagem (sem extensão)
#       * offset_x     : deslocamento horizontal a partir do centro (padrão 0)
#       * offset_y     : deslocamento vertical a partir do centro (padrão 0)
#       * button       : botão do mouse ('left', 'right', 'middle') – padrão 'left'
#       * clicks       : número de cliques (1 ou 2) – padrão 1
#
# Exemplos:
#   - "botao_ok"                                → clique central
#   - {"nome": "comecar", "offset_y": 20}       → clique 20 pixels abaixo do centro
#   - {"nome": "menu", "offset_x": -10, "offset_y": 5} → deslocamento arbitrário
#   - {"nome": "opcoes", "button": "right"}     → clique com botão direito no centro
#   - {"nome": "confirmar", "clicks": 2}        → duplo clique central

acoes = [
    "0-abrir_ui",
    {"nome": "1-comecar", "clicks": 2},
    {"nome": "2-impressora", "offset_y": -5},
    "3-seleciona_hp",
    {"nome": "4-imprimir", "clicks": 2}
]

# ==================== FUNÇÃO PRINCIPAL ====================
def localizar_e_clicar(config: Union[str, Dict]) -> bool:
    """
    Localiza uma imagem na tela e executa o clique conforme a configuração.

    Parâmetros:
        config: string com o nome da imagem ou dicionário com parâmetros.

    Retorna:
        bool: True se a operação foi bem-sucedida, False caso contrário.
    """
    # Normaliza a configuração para um dicionário com valores padrão
    if isinstance(config, str):
        config_dict = {"nome": config}
    elif isinstance(config, dict):
        config_dict = config.copy()
    else:
        if DEBUG: print(f"❌ Configuração inválida: {config}")
        return False

    nome_imagem = config_dict.get("nome")
    if not nome_imagem:
        if DEBUG: print("❌ Nome da imagem não especificado.")
        return False

    # Parâmetros com valores padrão
    offset_x = config_dict.get("offset_x", 0)
    offset_y = config_dict.get("offset_y", 0)
    button = config_dict.get("button", "left")
    clicks = config_dict.get("clicks", 1)

    caminho_imagem = f"./imagens/{nome_imagem}.png"

    try:
        # Verifica se o arquivo existe
        if not os.path.exists(caminho_imagem):
            if DEBUG: print(f"❌ Arquivo não encontrado: {caminho_imagem}")
            return False

        if DEBUG: print(f"🔍 Procurando: '{nome_imagem}' (offset: ({offset_x:+d}, {offset_y:+d}))...")

        localizacao = pyautogui.locateOnScreen(caminho_imagem, confidence=CONFIDENCE)

        if localizacao:
            centro_x = localizacao.left + localizacao.width // 2
            centro_y = localizacao.top + localizacao.height // 2
            
            alvo_x = centro_x + offset_x
            alvo_y = centro_y + offset_y
            
            pyautogui.moveTo(alvo_x, alvo_y, duration=MOUSE_MOVE_TIME)
            if DEBUG: print(f"✅ Imagem encontrada em centro=({centro_x}, {centro_y}) → alvo=({alvo_x}, {alvo_y})")
            
            time.sleep(CLICK_PAUSE)
            
            pyautogui.click(button=button, clicks=clicks)
            if DEBUG: print(f"🖱️  Clique realizado em '{nome_imagem}' (botão: {button}, {clicks} clique(s))")
            return True
        else:
            if DEBUG: print(f"❌ Imagem '{nome_imagem}' não encontrada na tela")
            return False

    except Exception as e:
        if DEBUG: print(f"❌ Erro ao processar imagem '{nome_imagem}': {str(e)}")
        return False

def rotina_clicar():
    if DEBUG: print("🚀 Iniciando script de automação...")
    if DEBUG: print(f"📋 Total de ações configuradas: {len(acoes)}")
    if DEBUG: print(f"⏰ Aguarde {INIT_TIME} segundo(s) para começar...")
    time.sleep(INIT_TIME)

    for config in acoes:
        localizar_e_clicar(config)
        time.sleep(ACTION_PAUSE)  # Pausa entre ações

    if DEBUG: print("✨ Script finalizado!")


# ==================== EXECUÇÃO PRINCIPAL ====================
def main():
    rotina_clicar()

if __name__ == "__main__":
    main()