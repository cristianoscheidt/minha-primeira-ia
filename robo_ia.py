import os
import time
from datetime import datetime
from google import genai

client = genai.Client()

# Tenta falar com a IA até 5 vezes caso o servidor esteja ocupado
for tentativa in range(1, 6):
    try:
        print(f"Tentativa {tentativa} de conectar com o Gemini...")
        resposta = client.models.generate_content(
            model="gemini-3.8-flash",
            contents="Crie uma frase curta de motivação e uma dica prática de produtividade para hoje."
        )
        break  # Se deu certo, sai do loop!
    except Exception as erro:
        print(f"Servidor ocupado ({erro}). Aguardando 15 segundos...")
        if tentativa == 5:
            raise  # Se falhar 5 vezes seguidas, avisa o erro
        time.sleep(15)

# Pega a data e hora atual
agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

# Salva o resultado no arquivo README.md do seu GitHub
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write("# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(resposta.text)

print("Automação concluída com sucesso!")
