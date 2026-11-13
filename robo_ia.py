import os
from datetime import datetime
from google import genai

# Inicializa o cliente oficial (lê a chave GEMINI_API_KEY automaticamente)
client = genai.Client()

# Pede para a IA gerar o conteúdo usando o modelo atual
resposta = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="Crie uma frase curta de motivação e uma dica prática de produtividade para hoje."
)

# Pega a data e hora atual
agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

# Salva o resultado no arquivo README.md do seu GitHub
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write("# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(resposta.text)

print("Automação concluída com sucesso!")
