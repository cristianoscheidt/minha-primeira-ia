
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COMPARADOR DE PREÇOS - FARMÁCIAS
Região: Balneário Camboriú - SC

Pesquisa via Tavily Search API.
Envia os resultados ao Telegram.

Farmácias:
1. Droga Raia
2. Drogaria São João
3. Panvel
4. Drogaria Catarinense
5. Pague Menos
"""

import os
import re
import sys
import time
import requests

from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo


# ==================================================
# CONFIGURAÇÕES
# ==================================================

TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 45
MAX_RESULTS = 5

FARMACIAS = {
    "Droga Raia": "drogaraia.com.br",
    "Drogaria São João": "farmaciasaojoao.com.br",
    "Panvel": "panvel.com",
    "Drogaria Catarinense": "drogariacatarinense.com.br",
    "Pague Menos": "paguemenos.com.br",
}


# ==================================================
# FORMATAÇÃO
# ==================================================

def brl(valor):
    return (
        f"R$ {valor:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def numero_preco(valor):

    if not valor:
        return None

    try:
        valor = str(valor).replace("R$", "").strip()

        if "," in valor:
            valor = valor.replace(".", "").replace(",", ".")

        numero = float(valor)

        if numero <= 0 or numero > 100000:
            return None

        return round(numero, 2)

    except (ValueError, TypeError):
        return None


def normalizar(texto):
    return re.sub(r"\s+", " ", str(texto)).strip()


# ==================================================
# TAVILY - PESQUISA
# ==================================================

def pesquisar_tavily(produto, farmacia, dominio, api_key):

    query = (
        f'{produto} preço promoção oferta '
        f'farmácia Balneário Camboriú SC'
    )

    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "include_domains": [dominio],
        "include_answer": False,
        "include_raw_content": False,
        "country": "Brazil"
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resposta = requests.post(
        TAVILY_URL,
        json=payload,
        headers=headers,
        timeout=TIMEOUT
    )

    resposta.raise_for_status()

    dados = resposta.json()

    resultados = []

    for item in dados.get("results", []):

        url = item.get("url", "")
        titulo = normalizar(item.get("title", ""))
        conteudo = normalizar(item.get("content", ""))

        if not url:
            continue

        host = (urlparse(url).hostname or "").lower()

        if not (host == dominio or host.endswith("." + dominio)):
            continue

        resultados.append({
            "farmacia": farmacia,
            "titulo": titulo,
            "url": url,
            "conteudo": conteudo,
            "score": item.get("score", 0),
            "data": item.get("published_date")
        })

    return resultados


# ==================================================
# IDENTIFICAÇÃO DE PRODUTO E EMBALAGEM
# ==================================================

def verificar_produto(produto, resultado):

    consulta = produto.lower()
    texto = (
        resultado["titulo"] + " " +
        resultado["conteudo"]
    ).lower()

    consulta_compacta = re.sub(r"[^a-z0-9]", "", consulta)
    texto_compacto = re.sub(r"[^a-z0-9]", "", texto)

    # Verifica marca Close Up
    if "closeup" in consulta_compacta:
        if "closeup" not in texto_compacto:
            return False

    # Verifica marca Colgate
    if "colgate" in consulta_compacta:
        if "colgate" not in texto_compacto:
            return False

    # Verifica tamanho solicitado
    tamanho = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(g|gr|ml)\b",
        consulta
    )

    if tamanho:

        quantidade = tamanho.group(1).replace(",", ".")
        unidade = tamanho.group(2)

        padrao = (
            rf"(?<!\d){re.escape(quantidade)}\s*"
            rf"(?:{unidade}|{'g' if unidade == 'gr' else unidade})\b"
        )

        resultado["tamanho_confirmado"] = bool(
            re.search(padrao, texto)
        )

    else:
        resultado["tamanho_confirmado"] = True

    return True


# ==================================================
# PREÇOS E PROMOÇÕES
# ==================================================

PADRAO_PRECO = (
    r"R\$\s*"
    r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
)


def extrair_precos(texto):

    encontrados = re.findall(
        PADRAO_PRECO,
        texto,
        flags=re.IGNORECASE
    )

    precos = []

    for item in encontrados:

        valor = numero_preco(item)

        if valor is not None and valor not in precos:
            precos.append(valor)

    return precos


def identificar_promocao(texto):

    texto = normalizar(texto)

    # Preço promocional por unidade seguido da quantidade.
    padrao_unitario = re.search(
        PADRAO_PRECO +
        r"\s*(?:cada|por unidade)?"
        r".{0,100}?"
        r"(?:levando|na compra de|comprando|a partir de)"
        r"\s*(\d{1,2})\s*"
        r"(?:unidades|unid\.?|un\.?)",
        texto,
        flags=re.IGNORECASE
    )

    if padrao_unitario:

        unitario = numero_preco(padrao_unitario.group(1))
        quantidade = int(padrao_unitario.group(2))

        if unitario and quantidade > 1:

            return {
                "unitario": unitario,
                "quantidade": quantidade,
                "total": round(unitario * quantidade, 2),
                "normal": identificar_preco_normal(texto)
            }

    # Quantidade por preço total do pacote.
    padrao_pacote = re.search(
        r"(\d{1,2})\s*"
        r"(?:unidades|unid\.?|un\.?)"
        r".{0,40}?"
        r"(?:por|a)\s*"
        + PADRAO_PRECO,
        texto,
        flags=re.IGNORECASE
    )

    if padrao_pacote:

        quantidade = int(padrao_pacote.group(1))
        total = numero_preco(padrao_pacote.group(2))

        if total and quantidade > 1:

            return {
                "unitario": round(total / quantidade, 2),
                "quantidade": quantidade,
                "total": total,
                "normal": identificar_preco_normal(texto)
            }

    # Formato: leve 4, pague 3.
    padrao_leve_pague = re.search(
        r"leve\s*(\d+)\s*,?\s*pague\s*(\d+)",
        texto,
        flags=re.IGNORECASE
    )

    if padrao_leve_pague:

        leve = int(padrao_leve_pague.group(1))
        pague = int(padrao_leve_pague.group(2))

        precos = extrair_precos(texto)

        if leve > pague and precos:

            unitario = precos[0]

            return {
                "unitario": round(
                    unitario * pague / leve, 2
                ),
                "quantidade": leve,
                "total": round(
                    unitario * pague, 2
                ),
                "normal": unitario
            }

    return None


def identificar_preco_normal(texto):

    padrao = re.search(
        r"(?:preço normal|preço regular|de)\s*:?\s*"
        + PADRAO_PRECO
        + r"\s*(?:por unidade|cada|a unidade)?",
        texto,
        flags=re.IGNORECASE
    )

    if padrao:
        return numero_preco(padrao.group(1))

    return None


def identificar_preco_unitario(texto):

    padrao = re.search(
        PADRAO_PRECO +
        r"\s*(?:por unidade|cada|a unidade)",
        texto,
        flags=re.IGNORECASE
    )

    if padrao:
        return numero_preco(padrao.group(1))

    return None


# ==================================================
# ORGANIZAÇÃO DOS RESULTADOS
# ==================================================

def formatar_resultado(item):

    linhas = []

    linhas.append(f"🏪 {item['farmacia']}")
    linhas.append(item["titulo"])
    linhas.append(item["url"])

    if not item["tamanho_confirmado"]:
        linhas.append(
            "⚠️ Embalagem não confirmada no trecho."
        )

    promo = identificar_promocao(item["conteudo"])

    if promo:

        linhas.append("")
        linhas.append(
            f"🔥 {brl(promo['unitario'])} "
            f"– levando {promo['quantidade']} unidades."
        )

        if promo["normal"]:

            linhas.append(
                f"Preço normal: {brl(promo['normal'])} "
                f"por unidade."
            )

        else:

            linhas.append(
                "Preço normal: não identificado."
            )

        linhas.append(
            f"Total de {promo['quantidade']} unidades: "
            f"{brl(promo['total'])}."
        )

        if promo["normal"]:

            economia = round(
                (promo["normal"] - promo["unitario"])
                * promo["quantidade"],
                2
            )

            if economia > 0:

                linhas.append(
                    f"Economia: {brl(economia)}."
                )

        item["preco_comparavel"] = promo["unitario"]

    else:

        unitario = identificar_preco_unitario(
            item["conteudo"]
        )

        precos = extrair_precos(item["conteudo"])

        if unitario:

            linhas.append(
                f"Preço unitário identificado: {brl(unitario)}."
            )

            item["preco_comparavel"] = unitario

        elif precos:

            linhas.append(
                "Valores encontrados no texto: "
                + ", ".join(brl(p) for p in precos[:4])
            )

            linhas.append(
                "⚠️ Não foi possível confirmar se o preço "
                "é unitário ou promocional."
            )

            item["preco_comparavel"] = None

        else:

            linhas.append(
                "Preço não identificado no resultado."
            )

            item["preco_comparavel"] = None

    if item.get("data"):
        linhas.append(
            f"Data informada pela fonte: {item['data']}"
        )

    trecho = item["conteudo"][:450]

    if trecho:
        linhas.append("")
        linhas.append("Trecho encontrado:")
        linhas.append(trecho)

    return "\n".join(linhas)


# ==================================================
# TELEGRAM
# ==================================================

def telegram_send(mensagem):

    token = (
        os.getenv("TELEGRAM_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID", ""
    ).strip()

    if not token or not chat_id:

        raise RuntimeError(
            "Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID."
        )

    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    partes = []

    while mensagem:

        if len(mensagem) <= 3900:
            partes.append(mensagem)
            break

        corte = mensagem.rfind("\n", 0, 3900)

        if corte < 1000:
            corte = 3900

        partes.append(mensagem[:corte])
        mensagem = mensagem[corte:].lstrip()

    for parte in partes:

        resposta = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": parte,
                "disable_web_page_preview": True
            },
            timeout=TIMEOUT
        )

        resposta.raise_for_status()

        if not resposta.json().get("ok"):
            raise RuntimeError(
                "Erro ao enviar mensagem ao Telegram."
            )


# ==================================================
# EXECUÇÃO PRINCIPAL
# ==================================================

def main():

    produto = (
        " ".join(sys.argv[1:]).strip()
        or os.getenv("PRODUCT", "").strip()
    )

    if not produto:
        raise SystemExit("Informe o nome do produto.")

    api_key = os.getenv(
        "TAVILY_API_KEY", ""
    ).strip()

    if not api_key:
        raise RuntimeError(
            "Secret TAVILY_API_KEY não encontrado no GitHub."
        )

    print(f"Produto pesquisado: {produto}")

    todos_resultados = []
    status = {}

    for farmacia, dominio in FARMACIAS.items():

        print(f"Pesquisando: {farmacia}")

        try:

            resultados = pesquisar_tavily(
                produto,
                farmacia,
                dominio,
                api_key
            )

            validos = []

            for item in resultados:

                if verificar_produto(produto, item):
                    validos.append(item)

            todos_resultados.extend(validos)

            status[farmacia] = (
                f"{len(validos)} resultado(s) encontrado(s)"
                if validos
                else "Nenhum produto correspondente encontrado"
            )

        except requests.HTTPError as erro:

            codigo = (
                erro.response.status_code
                if erro.response is not None
                else "desconhecido"
            )

            status[farmacia] = (
                f"Erro HTTP da Tavily: {codigo}"
            )

        except requests.RequestException as erro:

            status[farmacia] = (
                f"Falha de conexão: {erro.__class__.__name__}"
            )

        except Exception as erro:

            status[farmacia] = (
                f"Erro: {erro.__class__.__name__}"
            )

        time.sleep(0.5)

    # Remove duplicações.
    unicos = {}

    for item in todos_resultados:

        chave = (
            item["farmacia"],
            item["url"]
        )

        unicos[chave] = item

    todos_resultados = list(unicos.values())

    # Resultados com preço unitário explícito e embalagem confirmada.
    comparaveis = [
        item for item in todos_resultados
        if item.get("preco_comparavel") is not None
        and item.get("tamanho_confirmado", False)
    ]

    comparaveis.sort(
        key=lambda item: item["preco_comparavel"]
    )

    agora = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    ).strftime("%d/%m/%Y às %H:%M")

    linhas = [
        "🔎 COMPARADOR DE FARMÁCIAS",
        f"Produto: {produto}",
        "Região: Balneário Camboriú - SC",
        f"Consulta: {agora}",
        "",
        "RESULTADOS DA PESQUISA",
        "======================"
    ]

    if todos_resultados:

        for item in todos_resultados[:15]:

            linhas.append("")
            linhas.append(
                formatar_resultado(item)
            )
            linhas.append("----------------------")

    else:

        linhas.append(
            "Nenhum resultado correspondente foi encontrado."
        )

    if comparaveis:

        melhor = comparaveis[0]

        linhas.extend([
            "",
            "🏆 MENOR PREÇO UNITÁRIO IDENTIFICADO",
            f"{brl(melhor['preco_comparavel'])}",
            melhor["farmacia"],
            melhor["titulo"],
            melhor["url"]
        ])

    else:

        linhas.extend([
            "",
            "⚠️ Não foi possível estabelecer um menor preço "
            "unitário confiável nesta pesquisa."
        ])

    linhas.extend([
        "",
        "STATUS DAS CINCO FARMÁCIAS",
        "=========================="
    ])

    for farmacia, resultado in status.items():

        linhas.append(
            f"• {farmacia}: {resultado}"
        )

    linhas.extend([
        "",
        "OBSERVAÇÕES",
        "Os resultados vêm de páginas indexadas e trechos "
        "retornados pela pesquisa Tavily.",
        "Não representam confirmação de estoque ou preço "
        "em tempo real na unidade física.",
        "Promoções por quantidade somente são calculadas "
        "quando a condição aparece claramente no texto.",
        "Confirme o valor e a disponibilidade para retirada "
        "no site ou aplicativo antes de comprar."
    ])

    mensagem = "\n".join(linhas)

    print(mensagem)

    telegram_send(mensagem)

    print("Consulta enviada ao Telegram.")


if __name__ == "__main__":
    main()
