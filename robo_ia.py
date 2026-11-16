import os
import json
import random
import requests
from datetime import datetime
from google import genai
from google.genai import types

ARQUIVO_HISTORICO = "historico.json"
MAX_HISTORICO = 30  # quantas mensagens passadas o modelo deve evitar repetir

# Configura o cliente com limite de 15 segundos
client = genai.Client(
    http_options=types.HttpOptions(timeout=15000)
)

# ---------- 1. Carrega o histórico de mensagens já enviadas ----------
def carregar_historico():
    try:
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

historico = carregar_historico()

# ---------- 2. Sorteia temas para forçar variedade ----------
temas_motivacao = [
    "persistência", "coragem", "recomeços", "disciplina", "gratidão",
    "foco", "resiliência", "autoconfiança", "paciência", "propósito",
    "aprender com erros", "pequenos passos", "superação", "energia positiva",
]

temas_produtividade = [
    "gestão de tempo", "foco profundo", "organização da rotina",
    "priorização de tarefas", "pausas estratégicas", "redução de distrações",
    "planejamento semanal", "automação de tarefas repetitivas",
    "gestão de e-mails e mensagens", "hábitos matinais", "técnica Pomodoro",
    "revisão do dia", "delegação", "organização do ambiente de trabalho",
]

tema_mot = random.choice(temas_motivacao)
tema_prod = random.choice(temas_produtividade)

hoje = datetime.now()
dias_semana = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo"]
dia_semana = dias_semana[hoje.weekday()]
data_hoje = hoje.strftime("%d/%m/%Y")

# ---------- 3. Monta o prompt com contexto e lista de itens a evitar ----------
ultimas = historico[-MAX_HISTORICO:]
if ultimas:
    lista_evitar = "\n".join(f"- {item}" for item in ultimas)
    bloco_evitar = (
        "\n\nMensagens já enviadas anteriormente (NÃO repita as ideias, "
        "frases nem dicas destas):\n" + lista_evitar
    )
else:
    bloco_evitar = ""

prompt = f"""Hoje é {dia_semana}, {data_hoje}.

Crie, em português do Brasil:
1. Uma frase curta de motivação sobre o tema: {tema_mot}.
2. Uma dica prática de produtividade sobre o tema: {tema_prod}.

Regras:
- Seja original e diferente de qualquer mensagem anterior.
- Evite clichês comuns.
- A frase e a dica devem ser curtas (no máximo 2 linhas cada).
- Use o formato:
💪 Motivação: ...
⚡ Dica de produtividade: ...{bloco_evitar}"""

# ---------- 4. Gera o texto com temperatura alta ----------
resposta = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=1.2,
        top_p=0.95,
    ),
)

texto_final = resposta.text.strip()

# ---------- 5. Envia para o Telegram ----------
barra = chr(47)
token = os.environ["TELEGRAM_TOKEN"].strip()
chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()

url_telegram = f"https:{barra}{barra}api.telegram.org{barra}bot{token}{barra}sendMessage"

resposta_tg = requests.post(url_telegram, json={
    "chat_id": chat_id,
    "text": f"🤖 Sua dose diária de IA:\n\n{texto_final}"
})

if resposta_tg.status_code != 200:
    raise Exception(f"Erro ao enviar no Telegram: {resposta_tg.text}")

# ---------- 6. Atualiza o histórico ----------
historico.append(texto_final.replace("\n", " "))
historico = historico[-MAX_HISTORICO:]
with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
    json.dump(historico, f, ensure_ascii=False, indent=2)

# ---------- 7. Atualiza o README ----------
agora = hoje.strftime("%d/%m/%Y às %H:%M")
with open("README.md", "w", encoding="utf-8") as arquivo:
    arquivo.write("# 🤖 Diário da Minha Primeira IA\n\n")
    arquivo.write(f"**Última atualização:** {agora} (UTC)\n\n")
    arquivo.write(texto_final)

print("Automação concluída e enviada para o iPhone!")
