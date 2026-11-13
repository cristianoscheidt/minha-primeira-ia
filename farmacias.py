import os
import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

produto_busca = os.environ.get("PRODUTO", "creme dental colgate").strip()
termo_url = urllib.parse.quote(produto_busca)

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/html"
}

resultados_brutos = {}

# 1. Lojas com API de catálogo VTEX (São João, Catarinense, Pague Menos)
lojas_vtex = {
    "Farmácias São João": f"https://saojoaofarmacias.com.br{termo_url}?_from=0&_to=4",
    "Farmácia Catarinense": f"https://farmaciacatarinense.com.br{termo_url}?_from=0&_to=4",
    "Pague Menos": f"https://paguemenos.com.br{termo_url}?_from=0&_to=4",
}

for nome_loja, url in lojas_vtex.items():
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200 or r.status_code == 206:
            dados = r.json()
            itens = []
            for p in dados[:4]:
                nome = p.get("productName", "")
                try:
                    primeiro_item = next(iter(p.get("items", [])), {})
                    primeiro_seller = next(iter(primeiro_item.get("sellers", [])), {})
                    oferta = primeiro_seller.get("commertialOffer", {})
                    preco = oferta.get("Price", 0)
                    disponivel = oferta.get("AvailableQuantity", 0)
                    if preco > 0 and disponivel > 0:
                        itens.append(f"{nome}: R$ {preco:.2f}")
                except Exception:
                    continue
            resultados_brutos[nome_loja] = itens if itens else ["Nenhum item encontrado na API direta"]
        else:
            resultados_brutos[nome_loja] = [f"Bloqueio temporário (HTTP {r.status_code})"]
    except Exception as e:
        resultados_brutos[nome_loja] = [f"Erro de conexão: {str(e)[:40]}"]

# 2. Droga Raia e Panvel (leitura direta dos dados da página)
outras_lojas = {
    "Droga Raia": f"https://drogaraia.com.br{termo_url}",
    "Panvel": f"https://panvel.com{termo_url}"
}

for nome_loja, url in outras_lojas.items():
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            textos = []
            for script in soup.find_all("script", type="application/ld+json"):
                if script.string:
                    textos.append(script.string[:1500])
            if not textos:
                for el in soup.find_all(["h2", "h3", "span", "p"])[:60]:
                    txt = el.get_text(strip=True)
                    if "R$" in txt or any(palavra in txt.lower() for palavra in produto_busca.lower().split()):
                        textos.append(txt)
            resultados_brutos[nome_loja] = textos[:15] if textos else ["Sem dados visíveis no HTML"]
        else:
            resultados_brutos[nome_loja] = [f"Bloqueio temporário (HTTP {r.status_code})"]
    except Exception as e:
        resultados_brutos[nome_loja] = [f"Erro de conexão: {str(e)[:40]}"]

# 3. Gemini analisa e monta o ranking sem frete
client = genai.Client(http_options=types.HttpOptions(timeout=20000))

prompt = f"""
Você é um assistente de compras de farmácia. O usuário pesquisou por: "{produto_busca}".
Abaixo estão os dados brutos coletados diretamente das 5 farmácias:
{json.dumps(resultados_brutos, ensure_ascii=False, indent=2)}

Sua tarefa:
1. Identifique o produto mais relevante e equivalente entre as lojas (mesma marca e tamanho/quantidade).
2. Liste o menor preço encontrado em cada uma das 5 farmácias (São João, Droga Raia, Panvel, Catarinense, Pague Menos), ordenando do mais barato para o mais caro.
3. Ignore completamente frete (o usuário vai retirar na loja).
4. Se alguma farmácia não retornou preço ou bloqueou a consulta automática, indique claramente "Indisponível / Bloqueado no site" para essa loja, sem inventar valores.
5. Formate a resposta de forma limpa e direta para ser lida no celular (Telegram), sem usar asteriscos complexos que quebrem o texto.
"""

resposta = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents=prompt
)

texto_final = resposta.text

# 4. Envia para o Telegram no iPhone
barra = chr(47)
token = os.environ["TELEGRAM_TOKEN"].strip()
chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
url_telegram = f"https:{barra}{barra}api.telegram.org{barra}bot{token}{barra}sendMessage"

requests.post(url_telegram, json={
    "chat_id": chat_id,
    "text": f"💊 Pesquisa: {produto_busca.upper()}\n\n{texto_final}"
})

print("Pesquisa concluída e enviada!")
