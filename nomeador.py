import unicodedata
import re

def to_kebab_case(text):
    # Remove acentos e normaliza
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    # Minúsculas
    text = text.lower()
    # Remove caracteres especiais e troca por espaço
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    # Transforma espaços em hífens
    return "-".join(text.split())

print("--- Conversor Kebab-Case (Digite 'sair' para encerrar) ---")

while True:
    entrada = input("\nTexto: ").strip()
    
    # Condição de saída
    if entrada.lower() == 'sair' or not entrada:
        print("Encerrando... Até logo!")
        break
        
    resultado = to_kebab_case(entrada)
    print(f"Resultado: {resultado}")