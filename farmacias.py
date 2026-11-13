"""Comparador gratuito de preços em cinco farmácias.

Pesquisa páginas públicas de produtos por meio do HTML público do DuckDuckGo,
abre as páginas das próprias farmácias e tenta extrair preço estruturado
(JSON-LD / metadados). Não usa API paga nem confirma estoque de loja física.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PRODUCT = os.environ.get("PRODUCT_NAME", "").strip()
CITY = "Balneário Camboriú - SC"

PHARMACIES = [
    {"name": "Droga Raia", "domain": "drogaraia.com.br"},
    {"name": "Farmácias São João", "domain": "saojoaofarmacias.com.br"},
    {"name": "Panvel", "domain": "panvel.com"},
    {"name": "Drogaria Catarinense", "domain": "drogariacatarinense.com.br"},
    {"name": "Pague Menos", "domain": "paguemenos.com.br"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
STOPWORDS = {"de", "da", "do", "das", "dos", "com", "para", "em", "um", "uma", "e", "por", "kit"}


@dataclass
class ProductResult:
    pharmacy: str
    title: str | None = None
    price: float | None = None
    url: str | None = None
    availability: str = "Não verificada"
    status: str = "Preço não localizado"
    score: float = 0.0


class SearchResultParser(HTMLParser):
    """Extrai links de resultado do HTML simples do DuckDuckGo."""
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self._capture = False
        self._href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", ""):
            self._href = attrs.get("href")
            self._capture = True

    def handle_endtag(self, tag):
        if tag == "a" and self._capture:
            if self._href:
                self.links.append(self._href)
            self._href = None
            self._capture = False


def normalize_url(url: str) -> str:
    url = html.unescape(url)
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            url = unquote(target)
    return url


def tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.lower())
    return {word for word in words if len(word) > 1 and word not in STOPWORDS}


def similarity(query: str, title: str) -> float:
    wanted = tokens(query)
    found = tokens(title)
    if not wanted:
        return 0.0
    return len(wanted & found) / len(wanted)


def search_product_pages(pharmacy: dict, product: str) -> list[str]:
    query = f'site:{pharmacy["domain"]} {product}'
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    response = SESSION.get(url, timeout=25)
    response.raise_for_status()
    parser = SearchResultParser()
    parser.feed(response.text)

    found = []
    for raw_url in parser.links:
        link = normalize_url(raw_url)
        parsed = urlparse(link)
        if parsed.scheme in {"http", "https"} and pharmacy["domain"] in parsed.netloc:
            if link not in found:
                found.append(link)
        if len(found) >= 5:
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


def price_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("R$", "").replace(" ", "")
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def extract_product_data(page_url: str, query: str):
    response = SESSION.get(page_url, timeout=25, allow_redirects=True)
    response.raise_for_status()
    source = response.text

    # Nome e preço preferencialmente vêm dos dados estruturados oficiais da página.
    names = []
    prices = []
    availability = "Não verificada"

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        source, flags=re.I | re.S,
    ):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in walk_json(data):
            item_type = item.get("@type", [])
            if isinstance(item_type, str):
                item_type = [item_type]
            if any(str(t).lower() == "product" for t in item_type):
                name = item.get("name")
                if name:
                    names.append(str(name))
                offers = item.get("offers", [])
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers if isinstance(offers, list) else []:
                    if not isinstance(offer, dict):
                        continue
                    value = price_number(offer.get("price") or offer.get("lowPrice"))
                    currency = offer.get("priceCurrency", "BRL")
                    if value and currency == "BRL" and 0.5 <= value <= 50000:
                        prices.append(value)
                    offer_availability = str(offer.get("availability", "")).lower()
                    if "instock" in offer_availability:
                        availability = "Página indica disponível online; loja física não confirmada"
                    elif "outofstock" in offer_availability:
                        availability = "Página indica indisponível online"

    # Metadados comuns de páginas de produto, como fallback.
    if not names:
        for pattern in [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
            r'<title[^>]*>(.*?)</title>',
        ]:
            m = re.search(pattern, source, flags=re.I | re.S)
            if m:
                names.append(html.unescape(re.sub(r"\s+", " ", m.group(1))).strip())
                break

    if not prices:
        for pattern in [
            r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\']',
        ]:
            m = re.search(pattern, source, flags=re.I | re.S)
            if m:
                value = price_number(m.group(1))
                if value and 0.5 <= value <= 50000:
                    prices.append(value)
                    break

    title = names[0] if names else ""
    score = similarity(query, title)
    if not prices:
        return title, None, availability, score
    return title, min(prices), availability, score


def search_pharmacy(pharmacy: dict, product: str) -> ProductResult:
    result = ProductResult(pharmacy=pharmacy["name"])
    try:
        links = search_product_pages(pharmacy, product)
        if not links:
            result.status = "Busca pública não retornou página de produto"
            return result

        candidates = []
        for link in links[:4]:
            try:
                title, price, availability, score = extract_product_data(link, product)
                if title and score >= 0.5:
                    candidates.append((score, title, price, availability, link))
                time.sleep(0.4)
            except requests.RequestException:
                continue

        priced = [item for item in candidates if item[2] is not None]
        if not priced:
            if candidates:
                best = max(candidates, key=lambda item: item[0])
                result.title, result.url, result.score = best[1], best[4], best[0]
                result.status = "Produto localizado, mas preço não pôde ser extraído"
            else:
                result.status = "Não foi possível confirmar produto e preço"
            return result

        best = max(priced, key=lambda item: (item[0], -item[2]))
        result.score, result.title, result.price, result.availability, result.url = best
        result.status = "Preço extraído da página do produto"
        return result
    except requests.HTTPError as exc:
        result.status = f"Site/busca recusou a consulta (HTTP {exc.response.status_code})"
    except requests.RequestException as exc:
        result.status = f"Falha de conexão: {str(exc)[:90]}"
    except Exception as exc:
        result.status = f"Não foi possível interpretar a página: {str(exc)[:90]}"
    return result


def brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def telegram_send(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = SESSION.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }, timeout=25)
    response.raise_for_status()


def main() -> int:
    if not PRODUCT:
        print("Informe um produto em PRODUCT_NAME.", file=sys.stderr)
        return 2

    print(f"Pesquisando: {PRODUCT}")
    results = []
    for pharmacy in PHARMACIES:
        print(f"Consultando {pharmacy['name']}...")
        results.append(search_pharmacy(pharmacy, PRODUCT))

    found = [item for item in results if item.price is not None]
    found.sort(key=lambda item: item.price)

    lines = [
        "🛒 COMPARADOR DE FARMÁCIAS",
        f"Produto: {PRODUCT}",
        f"Região de referência: {CITY}",
        f"Consulta: {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}",
        "",
    ]
    for item in results:
        lines.append(f"🏪 {item.pharmacy}")
        if item.price is not None:
            lines.append(f"💰 {brl(item.price)}")
            if item.title:
                lines.append(f"Produto: {item.title[:180]}")
            if item.url:
                lines.append(item.url)
            lines.append(f"Retirada: {item.availability}")
        else:
            lines.append(item.status)
            if item.url:
                lines.append(item.url)
        lines.append("")

    if found:
        best = found[0]
        lines.extend(["🏆 MENOR PREÇO ENCONTRADO", f"{best.pharmacy}: {brl(best.price)}", best.url or "", ""])
    else:
        lines.extend(["⚠️ Nenhum preço pôde ser confirmado nesta execução.", ""])

    lines.extend([
        "Observações:",
        "• Consulta gratuita a páginas públicas; sites podem limitar ou bloquear acessos automatizados.",
        "• Preços online podem diferir dos preços e estoques das lojas físicas.",
        "• A disponibilidade para retirada em Balneário Camboriú não é confirmada automaticamente.",
        "• Confira o produto, preço final e unidade selecionada no site antes de comprar.",
    ])
    telegram_send("\n".join(lines)[:4000])
    print("Comparativo enviado ao Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
