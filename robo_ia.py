import os
import requests
from datetime import datetime
from google import genai
from google.genai import types

# Configura o cliente com limite máximo de 15 segundos para não travar
client = genai.Client(
    http_options=types.HttpOptions(timeout=15000)
)

# Usa o modelo Flash-Lite, que é muito mais rápido e sem fila
resposta = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents="Crie uma frase curta de motivação e uma dica prática de produtividade para hoje."
)

texto_final = resposta.text

# Envia a mensagem para o seu Telegram no iPhone
token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
url_telegram = f"https://telegram.org{token}/sendMessage"

resposta_tg = requests.post(url_telegram, json={
    "chat_id": chat_id,
    "text": f"🤖 Sua dose diária de IA:\n\n{texto_final}"
})

# Verifica se o Telegram aceitou a mensagem
if resposta_tg.status_code != 200:
    raise Exception(f"Erro ao enviar no Telegram: {resposta_tg.text}")

# Salva o histórico no GitHub
agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write("# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(texto_final)

print("Automação concluída e enviada para o iPhone!")
