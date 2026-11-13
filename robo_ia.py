import os
import time
import requests
from datetime import datetime
from google import genai

client = genai.Client()

for tentativa in range(1, 6):
    try:
        print(f"Tentativa {tentativa} de conectar com o Gemini...")
        resposta = client.models.generate_content(
            model="gemini-3.8-flash",
            contents="Crie uma frase curta de motivação e uma dica prática de produtividade para hoje."
        )
        break
    except Exception as erro:
        print(f"Servidor ocupado ({erro}). Aguardando 15 segundos...")
        if tentativa == 5:
            raise
        time.sleep(15)

texto_final = resposta.text

# Envia a mensagem para o seu Telegram no iPhone
token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
url_telegram = f"https://telegram.org{token}/sendMessage"

requests.post(url_telegram, json={
    "chat_id": chat_id,
    "text": f"🤖 *Sua dose diária de IA:*\n\n{texto_final}",
    "parse_mode": "Markdown"
})

# Também salva o histórico no GitHub
agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write("# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(texto_final)

print("Mensagem enviada para o Telegram com sucesso!")
