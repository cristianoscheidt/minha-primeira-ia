#!/usr/bin/env python3
"""Busca candidatos de preços nas cinco farmácias e envia o resumo ao Telegram.

A busca usa o HTML público do DuckDuckGo e consulta páginas públicas dos produtos.
Não é integração oficial com estoque: preços e disponibilidade devem ser confirmados
no site/app da farmácia antes da compra.
"""

import json
import os
import re
import sys
import time
from html import unescape
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

FARMACIAS = {
    "Droga Raia": ["drogaraia.com.br"],
    "Drogaria São João": ["farmaciasaojoao.com.br", "saojoaofarmacias.com.br"],
    "Panvel": ["panvel.com"],
    "Drogaria Catarinense": ["drogariacatarinense.com.br"],
    "Pague Menos": ["paguemenos.com.br"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TIMEOUT = 18
MAX_RESULTS_PER_STORE = 3


def money(value):
    if value is None:
        return None
    try:
        number = float(str(value).replace("R$", "").replace(" ", "").replace(".", "").replace(",", "."))
        if number <= 0 or number > 100000:
            return None
        return number
    except (TypeError, ValueError):
        return None


def format_brl(value):
    return (f"R$ {value:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def search_store(session, store, domains, product):
    site_filter = " OR ".join(f"site:{domain}" for domain in domains)
    query = f'{product} ({site_filter})'
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    seen = set()
    for anchor in soup.select("a.result__a"):
        href = anchor.get("href", "")
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not href.startswith("http") or not title:
            continue
        host = (urlparse(href).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in domains):
            continue
        if href in seen:
            continue
        seen.add(href)
        parent = anchor.find_parent(class_="result")
        snippet_node = parent.select_one(".result__snippet") if parent else None
        snippet = " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node else ""
        found.append({"store": store, "title": title, "url": href, "snippet": snippet})
        if len(found) >= MAX_RESULTS_PER_STORE:
            break
    return found


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_price(session, item):
    """Prioriza schema.org Product/Offer; fallback conservador no texto da página."""
    try:
        response = session.get(item["url"], headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for obj in walk_json(data):
                if "price" in obj:
                    price = money(obj.get("price"))
                    if price:
                        item["price"] = price
                        item["price_source"] = "dados estruturados da página"
                        return item
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = money(offers.get("price") or offers.get("lowPrice"))
                    if price:
                        item["price"] = price
                        item["price_source"] = "oferta estruturada da página"
                        return item
                if isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            price = money(offer.get("price") or offer.get("lowPrice"))
                            if price:
                                item["price"] = price
                                item["price_source"] = "oferta estruturada da página"
                                return item
        # Fallback: somente um preço explícito próximo a R$ no conteúdo visível.
        text = " ".join(soup.get_text(" ", strip=True).split())
        matches = re.findall(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", text)
        prices = [money(m) for m in matches]
        prices = [p for p in prices if p]
        if prices:
            item["price"] = min(prices)
            item["price_source"] = "texto da página (confirmar no site)"
    except requests.RequestException as exc:
        item["error"] = f"Não foi possível abrir a página: {exc.__class__.__name__}"
    return item


def telegram_send(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID nos GitHub Secrets.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem: {payload}")


def main():
    product = " ".join(sys.argv[1:]).strip() or os.environ.get("PRODUCT", "").strip()
    if not product:
        raise SystemExit("Informe o produto no campo produto do GitHub Actions.")

    session = requests.Session()
    candidates = []
    errors = []
    for store, domains in FARMACIAS.items():
        try:
            results = search_store(session, store, domains, product)
            if not results:
                errors.append(f"{store}: nenhum resultado encontrado na busca pública")
            candidates.extend(results)
        except requests.RequestException as exc:
            errors.append(f"{store}: busca indisponível ({exc.__class__.__name__})")
        time.sleep(1)

    priced = []
    for item in candidates:
        priced.append(extract_price(session, item))
        time.sleep(0.5)

    with_price = [x for x in priced if x.get("price")]
    with_price.sort(key=lambda x: x["price"])

    lines = [f"🔎 COMPARADOR DE FARMÁCIAS", f"Produto pesquisado: {product}", "Referência: Balneário Camboriú - SC", ""]
    if with_price:
        lines.append("RESULTADOS COM PREÇO IDENTIFICADO:")
        shown_stores = set()
        for item in with_price:
            if item["store"] in shown_stores:
                continue
            shown_stores.add(item["store"])
            lines.append(f"\n{item['store']}: {format_brl(item['price'])}")
            lines.append(item["title"][:150])
            lines.append(item["url"])
            lines.append(f"Fonte do preço: {item.get('price_source', 'não identificada')}")
        best = with_price[0]
        lines.extend(["", f"🏆 Menor preço encontrado: {format_brl(best['price'])} — {best['store']}"])
    else:
        lines.append("Não consegui identificar preços confiáveis nesta consulta.")

    missing = [name for name in FARMACIAS if name not in {x["store"] for x in with_price}]
    if missing:
        lines.extend(["", "Sem preço confirmado nesta consulta: " + ", ".join(missing)])
    if errors:
        lines.extend(["", "Observações da pesquisa:", *[f"• {e}" for e in errors]])
    lines.extend(["", "⚠️ Preços online podem variar por loja, cadastro, promoção e horário. Estoque para retirada não é confirmado por esta busca. Confira o preço e a disponibilidade no site/app antes de sair."])

    message = "\n".join(lines)
    # Telegram limita mensagens a 4096 caracteres.
    telegram_send(message[:4000])
    print(message)


if __name__ == "__main__":
    main()
