import os
import json
import urllib.parse
import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from google import genai
from google.genai import types

produto_busca = os.environ.get("PRODUTO", "creme dental colgate").strip()
termo_url = urllib.parse.quote(produto_busca)

urls_lojas = {
    "Farmácias São João": f"https://saojoaofarmacias.com.br{termo_url}?_q={termo_url}&map=ft",
    "Droga Raia": f"https://drogaraia.com.br{termo_url}",
    "Panvel": f"https://panvel.com{termo_url}",
    "Farmácia Catarinense": f"https://farmaciacatarinense.com.br{termo_url}?_q={termo_url}&map=ft",
    "Pague Menos": f"https://paguemenos.com.br{termo_url}?_q={termo_url}&map=ft"
}

resultados_brutos = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        locale="pt-BR"
    )
    page = context.new_page()
    stealth_sync(page)

    for nome_loja, url in urls_lojas.items():
        try:
            print(f"Abrindo {nome_loja}...")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(4000)  # Aguarda os preços carregarem na tela
            
            # Extrai apenas as linhas da página que contêm R$ ou o nome do produto
            texto_pagina = page.inner_text("body")
            linhas_uteis = []
            for linha in texto_pagina.split("\n"):
                linha_limpa = linha.strip()
                if len(linha_limpa) > 2 and ("R$" in linha_limpa or any(w in linha_limpa.lower() for w in produto_busca.lower().split())):
                    linhas_uteis.append(linha_limpa)
            
            resultados_brutos[nome_loja] = linhas_uteis[:35] if linhas_uteis else ["Página carregou sem preços visíveis"]
        except Exception as e:
            resultados_brutos[nome_loja] = [f"Falha ao abrir página: {str(e)[:50]}"]

    browser.close()

# Envia os textos lidos das telas para o Gemini organizar
client = genai.Client(http_options=types.HttpOptions(timeout=20000))

prompt = f"""
Você é um assistente de compras de farmácia. O usuário pesquisou por: "{produto_busca}".
Abaixo estão os textos extraídos diretamente das telas de busca das 5 farmácias:
{json.dumps(resultados_brutos, ensure_ascii=False, indent=2)}

Sua tarefa:
1. Identifique o produto mais equivalente entre as lojas (mesma marca e quantidade/gramagem).
2. Liste o menor preço encontrado em cada uma das 5 farmácias (São João, Droga Raia, Panvel, Catarinense, Pague Menos), ordenando do mais barato para o mais caro.
3. Ignore frete (retirada na loja).
4. Se alguma loja bloqueou ou não mostrou preço, escreva "Bloqueado / Não encontrado" apenas para ela, sem inventar números.
5. Responda de forma limpa e direta para o Telegram (sem asteriscos complexos).
"""

resposta = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents=prompt
)

texto_final = resposta.text

# Envia para o Telegram
barra = chr(47)
token = os.environ["TELEGRAM_TOKEN"].strip()
chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
url_telegram = f"https:{barra}{barra}api.telegram.org{barra}bot{token}{barra}sendMessage"

requests.post(url_telegram, json={
    "chat_id": chat_id,
    "text": f"💊 Pesquisa: {produto_busca.upper()}\n\n{texto_final}"
})

print("Pesquisa finalizada!")
