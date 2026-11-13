
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COMPARADOR DE FARMÁCIAS
Região de referência: Balneário Camboriú - SC

Consulta:
- Droga Raia
- Drogaria São João
- Panvel
- Drogaria Catarinense
- Pague Menos

Não utiliza Tavily, Serper, Gemini ou DuckDuckGo.
Tenta consultar catálogos públicos e páginas de busca das lojas.

Atenção:
Preços e estoque dependem das informações disponibilizadas
por cada farmácia. A disponibilidade para retirada precisa
ser confirmada no site ou aplicativo da loja.
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


TIMEOUT = 20
MAX_RESULTS = 12

FARMACIAS = {
    "Droga Raia": {
        "domain": "https://www.drogaraia.com.br",
        "search": "https://www.drogaraia.com.br/search?w={query}",
    },
    "Drogaria São João": {
        "domain": "https://www.farmaciasaojoao.com.br",
        "search": "https://www.farmaciasaojoao.com.br/busca?query={query}",
    },
    "Panvel": {
        "domain": "https://www.panvel.com",
        "search": "https://www.panvel.com/panvel/busca?termo={query}",
    },
    "Drogaria Catarinense": {
        "domain": "https://www.drogariacatarinense.com.br",
        "search": "https://www.drogariacatarinense.com.br/busca?ft={query}",
    },
    "Pague Menos": {
        "domain": "https://www.paguemenos.com.br",
        "search": "https://www.paguemenos.com.br/busca?ft={query}",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# --------------------------------------------------
# FORMATAÇÃO E CONVERSÃO DE PREÇOS
# --------------------------------------------------

def brl(value):
    return (
        f"R$ {value:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def to_number(value):
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        text = text.replace("R$", "").replace(" ", "")

        if not text:
            return None

        if "," in text:
            text = text.replace(".", "").replace(",", ".")

        try:
            number = float(text)
        except ValueError:
            return None

    if number <= 0 or number > 100000:
        return None

    return round(number, 2)


def extract_prices(text):
    pattern = (
        r"R\$\s*"
        r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|"
        r"[0-9]+,[0-9]{2})"
    )

    matches = re.findall(pattern, text, flags=re.I)

    return [
        value
        for value in (to_number(item) for item in matches)
        if value is not None
    ]


# --------------------------------------------------
# VALIDAÇÃO DO PRODUTO
# --------------------------------------------------

def product_matches(query, title):

    q = query.lower()
    t = title.lower()

    brands = [
        "colgate",
        "close up",
        "closeup",
        "oral-b",
        "sensodyne",
    ]

    for brand in brands:
        if brand in q:
            if brand.replace(" ", "") not in t.replace(" ", ""):
                return False

    size = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(g|gr|ml)\b",
        q,
    )

    if size:
        amount = size.group(1).replace(",", ".")
        unit = size.group(2)

        pattern = (
            rf"\b{re.escape(amount.rstrip('0').rstrip('.'))}"
            rf"\s*(?:g|gr|ml)\b"
        )

        if not re.search(pattern, t.replace(",", ".")):
            return False

    return True


# --------------------------------------------------
# LEITURA DE DADOS JSON
# --------------------------------------------------

def walk_objects(value):

    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk_objects(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def extract_json_products(soup, store, page_url, query):

    results = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):

        try:
            data = json.loads(
                script.string or script.get_text()
            )
        except (json.JSONDecodeError, TypeError):
            continue

        for obj in walk_objects(data):

            product_type = obj.get("@type", "")

            if isinstance(product_type, list):
                product_type = " ".join(product_type)

            if "Product" not in str(product_type):
                continue

            title = obj.get("name") or ""

            if not title:
                continue

            if not product_matches(query, title):
                continue

            offers = obj.get("offers") or {}

            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            if not isinstance(offers, dict):
                continue

            price = to_number(
                offers.get("price")
                or offers.get("lowPrice")
            )

            if not price:
                continue

            link = obj.get("url") or page_url

            results.append({
                "store": store,
                "title": title,
                "url": urljoin(page_url, link),
                "price": price,
                "list_price": None,
                "available": offers.get("availability"),
                "source": "Dados estruturados da página",
                "promotion_text": " ".join(
                    soup.get_text(" ", strip=True).split()
                ),
            })

    return results


# --------------------------------------------------
# CONSULTA AO CATÁLOGO VTEX
# --------------------------------------------------

def search_vtex(session, store, config, query):

    base = config["domain"]

    api_url = (
        f"{base}/api/catalog_system/pub/products/search/"
        f"{quote(query)}?_from=0&_to=49"
    )

    response = session.get(
        api_url,
        headers={
            **HEADERS,
            "Accept": "application/json",
        },
        timeout=TIMEOUT,
    )

    if response.status_code != 200:
        return []

    try:
        products = response.json()
    except ValueError:
        return []

    if not isinstance(products, list):
        return []

    results = []

    for product in products:

        if not isinstance(product, dict):
            continue

        title = (
            product.get("productName")
            or product.get("productTitle")
            or ""
        )

        if not product_matches(query, title):
            continue

        items = product.get("items") or []

        offers = []

        for item in items:

            sellers = item.get("sellers") or []

            for seller in sellers:

                commercial = (
                    seller.get("commertialOffer")
                    or seller.get("commercialOffer")
                    or {}
                )

                price = to_number(
                    commercial.get("Price")
                )

                list_price = to_number(
                    commercial.get("ListPrice")
                )

                if price:

                    offers.append({
                        "price": price,
                        "list_price": list_price,
                        "available": commercial.get(
                            "AvailableQuantity"
                        ),
                    })

        if not offers:
            continue

        offer = min(
            offers,
            key=lambda item: item["price"],
        )

        link = product.get("link") or ""

        results.append({
            "store": store,
            "title": title,
            "url": urljoin(base, link),
            "price": offer["price"],
            "list_price": (
                offer["list_price"]
                if offer["list_price"]
                and offer["list_price"] > offer["price"]
                else None
            ),
            "available": offer["available"],
            "source": "Catálogo público da loja",
            "promotion_text": "",
        })

        if len(results) >= MAX_RESULTS:
            break

    return results


# --------------------------------------------------
# CONSULTA À BUSCA INTERNA DA FARMÁCIA
# --------------------------------------------------

def search_html(session, store, config, query):

    search_url = config["search"].format(
        query=quote(query)
    )

    response = session.get(
        search_url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    if response.status_code != 200:
        return [], (
            f"Busca interna respondeu HTTP "
            f"{response.status_code}"
        )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = extract_json_products(
        soup,
        store,
        response.url,
        query,
    )

    if results:
        return results[:MAX_RESULTS], None

    selectors = [
        "[data-product-name]",
        ".product-item",
        ".product-card",
        ".shelf-item",
        "article",
    ]

    for selector in selectors:

        for node in soup.select(selector):

            title = node.get("data-product-name") or ""

            if not title:

                title_node = node.select_one(
                    "h2, h3, .product-name, "
                    ".product-title, a[title]"
                )

                if title_node:

                    title = (
                        title_node.get("title")
                        or title_node.get_text(
                            " ",
                            strip=True,
                        )
                    )

            if not title:
                continue

            if not product_matches(query, title):
                continue

            text = " ".join(
                node.get_text(" ", strip=True).split()
            )

            prices = extract_prices(text)

            if not prices:
                continue

            link_node = node.select_one("a[href]")

            link = (
                urljoin(
                    response.url,
                    link_node.get("href"),
                )
                if link_node
                else response.url
            )

            results.append({
                "store": store,
                "title": title,
                "url": link,
                "price": min(prices),
                "list_price": (
                    max(prices)
                    if len(prices) > 1
                    else None
                ),
                "available": None,
                "source": "Preço visível no cartão",
                "promotion_text": text,
            })

            if len(results) >= MAX_RESULTS:
                break

        if results:
            break

    return results[:MAX_RESULTS], None


# --------------------------------------------------
# IDENTIFICAÇÃO DE PROMOÇÕES
# --------------------------------------------------

def promotion_details(text, observed_price):

    clean = " ".join(text.split())

    quantity = None

    patterns = [
        r"(?:levando|na compra de|com a compra de|"
        r"a partir de|leve)\s*(\d{1,2})\s*"
        r"(?:unidades|unid\.?|un\.?|produtos)",

        r"(\d{1,2})\s*"
        r"(?:unidades|unid\.?|un\.?)\s*"
        r"(?:por|a)\s*R\$",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            clean,
            flags=re.I,
        )

        if match:
            quantity = int(match.group(1))
            break

    normal_price = None

    normal_match = re.search(
        r"(?:preço\s*normal|de)\s*:?\s*"
        r"R\$\s*"
        r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|"
        r"[0-9]+,[0-9]{2})",
        clean,
        flags=re.I,
    )

    if normal_match:
        normal_price = to_number(
            normal_match.group(1)
        )

    pack_match = re.search(
        r"(\d{1,2})\s*"
        r"(?:unidades|unid\.?|un\.?)\s*"
        r"(?:por|a)\s*R\$\s*"
        r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|"
        r"[0-9]+,[0-9]{2})",
        clean,
        flags=re.I,
    )

    if pack_match:

        quantity = int(pack_match.group(1))

        total_pack = to_number(
            pack_match.group(2)
        )

        if total_pack and quantity:
            observed_price = round(
                total_pack / quantity,
                2,
            )

    if quantity and observed_price:

        total = round(
            observed_price * quantity,
            2,
        )

        savings = None

        if normal_price and normal_price > observed_price:
            savings = round(
                (normal_price - observed_price)
                * quantity,
                2,
            )

        return {
            "unit_price": observed_price,
            "quantity": quantity,
            "total": total,
            "normal_price": normal_price,
            "savings": savings,
        }

    return None


# --------------------------------------------------
# FORMATAÇÃO DOS RESULTADOS
# --------------------------------------------------

def format_product(item):

    lines = [
        f"{item['store']}: {brl(item['price'])}",
        item["title"],
        item["url"],
    ]

    promo = promotion_details(
        item.get("promotion_text", ""),
        item["price"],
    )

    if promo:

        lines.extend([
            "",
            f"PROMOÇÃO: {brl(promo['unit_price'])} "
            f"– levando {promo['quantity']} unidades.",
        ])

        if promo["normal_price"]:

            lines.append(
                f"Preço normal: "
                f"{brl(promo['normal_price'])} "
                f"por unidade."
            )

        else:

            lines.append(
                "Preço normal: não identificado."
            )

        lines.append(
            f"Total de {promo['quantity']} unidades: "
            f"{brl(promo['total'])}."
        )

        if promo["savings"] is not None:

            lines.append(
                f"Economia na quantidade mínima: "
                f"{brl(promo['savings'])}."
            )

    elif (
        item.get("list_price")
        and item["list_price"] > item["price"]
    ):

        lines.append(
            f"Preço anterior/listado: "
            f"{brl(item['list_price'])}."
        )

    if item.get("available") is not None:

        lines.append(
            f"Disponibilidade informada pela página: "
            f"{item['available']}."
        )

    return "\n".join(lines)


# --------------------------------------------------
# ENVIO PARA O TELEGRAM
# --------------------------------------------------

def telegram_send(message):

    token = (
        os.getenv("TELEGRAM_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        "",
    ).strip()

    if not token or not chat_id:

        missing = []

        if not token:
            missing.append("TELEGRAM_TOKEN")

        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")

        raise RuntimeError(
            "Secrets ausentes no ambiente: "
            + ", ".join(missing)
        )

    endpoint = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    chunks = []
    remaining = message

    while remaining:

        if len(remaining) <= 3900:
            chunks.append(remaining)
            break

        cut = remaining.rfind(
            "\n",
            0,
            3900,
        )

        if cut < 1000:
            cut = 3900

        chunks.append(remaining[:cut])

        remaining = remaining[cut:].lstrip()

    for chunk in chunks:

        response = requests.post(
            endpoint,
            data={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

        if not payload.get("ok"):

            raise RuntimeError(
                "Telegram recusou a mensagem: "
                + str(
                    payload.get(
                        "description",
                        "erro desconhecido",
                    )
                )
            )


# --------------------------------------------------
# EXECUÇÃO PRINCIPAL
# --------------------------------------------------

def main():

    query = (
        " ".join(sys.argv[1:]).strip()
        or os.getenv("PRODUCT", "").strip()
    )

    if not query:

        raise SystemExit(
            "Informe o produto no campo produto "
            "do GitHub Actions."
        )

    session = requests.Session()
    session.headers.update(HEADERS)

    all_results = []
    store_status = {}

    for store, config in FARMACIAS.items():

        print(f"Consultando {store}...")

        try:

            results = search_vtex(
                session,
                store,
                config,
                query,
            )

            error = None

            if not results:

                results, error = search_html(
                    session,
                    store,
                    config,
                    query,
                )

            all_results.extend(results)

            if results:

                store_status[store] = (
                    f"{len(results)} produto(s) encontrado(s)"
                )

            else:

                store_status[store] = (
                    error or "Nenhum preço identificado"
                )

        except requests.RequestException as exc:

            store_status[store] = (
                f"Erro de conexão: {exc.__class__.__name__}"
            )

        except Exception as exc:

            store_status[store] = (
                f"Falha: {exc.__class__.__name__}"
            )

        time.sleep(0.7)

    # Remove resultados duplicados.

    unique = {}

    for item in all_results:

        key = (
            item["store"],
            item["url"],
            item["title"].lower(),
        )

        unique[key] = item

    all_results = list(unique.values())

    all_results.sort(
        key=lambda item: item["price"]
    )

    lines = [
        "🔎 COMPARADOR DE FARMÁCIAS",
        f"Produto pesquisado: {query}",
        "Região: Balneário Camboriú - SC",
        "",
        "Preços de catálogos e páginas públicas.",
        "Retirada em loja não confirmada automaticamente.",
        "",
    ]

    if all_results:

        lines.append(
            "RESULTADOS COM PREÇO IDENTIFICADO:"
        )

        for item in all_results[:20]:

            lines.extend([
                "",
                format_product(item),
            ])

        best = all_results[0]

        lines.extend([
            "",
            "🏆 MENOR PREÇO ENCONTRADO:",
            f"{brl(best['price'])} – {best['store']}",
        ])

    else:

        lines.append(
            "Não foi possível identificar preços "
            "automaticamente nesta consulta."
        )

    lines.extend([
        "",
        "STATUS POR FARMÁCIA:",
    ])

    for store, status in store_status.items():

        lines.append(
            f"• {store}: {status}"
        )

    lines.extend([
        "",
        "IMPORTANTE:",
        "Promoções por quantidade só são calculadas "
        "quando a condição aparece explicitamente "
        "nos dados da página.",
        "Confirme o preço final e o estoque para retirada "
        "no site ou aplicativo antes de ir à loja.",
    ])

    message = "\n".join(lines)

    print(message)

    telegram_send(message)


if __name__ == "__main__":
    main()
