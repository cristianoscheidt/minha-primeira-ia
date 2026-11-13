import os
from datetime import datetime
import google.generativeai as genai

# Pega a chave secreta que você salvou no GitHub
chave = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=chave)

# Escolhe o modelo rápido e gratuito do Gemini
modelo = genai.GenerativeModel("gemini-2.5-flash")

# Pede para a IA gerar um conteúdo
resposta = modelo.generate_content(
    "Crie uma frase curta de motivação e uma dica prática de produtividade para hoje."
)

# Pega a data e hora atual
agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

# Salva o resultado no arquivo README.md do seu GitHub
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write(f"# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(resposta.text)

print("Automação concluída com sucesso!")
