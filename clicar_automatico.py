import pyautogui
import time
import os

# Configurações
pyautogui.PAUSE = 0.3  # Pausa de 0.5 segundos entre ações
pyautogui.FAILSAFE = True  # Ativa o failsafe (mover mouse para canto superior esquerdo)

INIT_TIME = 1
ACTION_PAUSE = 2
CLICK_PAUSE = 0.3
MOUSE_MOVE_TIME = 0.15

# Array com nomes das imagens (sem extensão)
nomes_imagens = [
    "0-abrir_ui",
    "1-comecar",
    "2-impressora"
]

def localizar_e_clicar(nome_imagem):
    """
    Função para localizar uma imagem na tela e clicar nela
    """
    caminho_imagem = f"./imagens/{nome_imagem}.png"
    
    try:
        # Verifica se o arquivo existe
        if not os.path.exists(caminho_imagem):
            print(f"❌ Arquivo não encontrado: {caminho_imagem}")
            return False
        
        print(f"🔍 Procurando: {nome_imagem}...")
        
        # Localiza a imagem na tela
        localizacao = pyautogui.locateOnScreen(caminho_imagem, confidence=0.8)
        
        if localizacao:
            # Obtém o centro da imagem
            centro_x = localizacao.left + localizacao.width // 2
            centro_y = localizacao.top + localizacao.height // 2
            
            # Move o mouse para a posição
            pyautogui.moveTo(centro_x, centro_y, duration=MOUSE_MOVE_TIME)
            print(f"✅ Imagem '{nome_imagem}' encontrada em: ({centro_x}, {centro_y})")
            
            # Aguarda um momento antes de clicar
            time.sleep(CLICK_PAUSE)
            
            # Clica na posição
            pyautogui.click()
            print(f"🖱️ Clique realizado em '{nome_imagem}'")
            
            return True
        else:
            print(f"❌ Imagem '{nome_imagem}' não encontrada na tela")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao processar imagem '{nome_imagem}': {str(e)}")
        return False

def main():
    """
    Função principal que processa todas as imagens
    """
    print("🚀 Iniciando script de automação...")
    print(f"📋 Total de imagens: {len(nomes_imagens)}")
    print(f"⏰ Aguarde {INIT_TIME} segundo para começar...")
    time.sleep(INIT_TIME)
    
    for nome in nomes_imagens:
        localizar_e_clicar(nome)
        time.sleep(ACTION_PAUSE)  # Pequena pausa entre cada ação
    
    print("✨ Script finalizado!")

if __name__ == "__main__":
    main()