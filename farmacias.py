import os, re, urllib.parse, requests
from playwright.sync_api import sync_playwright

PRODUTO = os.environ["PRODUTO"].strip()
Q = urllib.parse.quote(PRODUTO)

# ⚠️ URLs e seletores são ponto de partida: vamos ajustar após o primeiro teste
FARMACIAS = [
    {"nome": "Drogasil",   "url": f"https://www.drogasil.com.br/search?w={Q}",
     "card": "[data-testid='product-card'], article", "preco": None},
    {"nome": "Droga Raia", "url": f"https://www.drogaraia.com.br/search?w={Q}",
     "card": "[data-testid='product-card'], article", "preco": None},
    {"nome": "Pague Menos", "url": f"https://www.paguemenos.com.br/{Q}?_q={Q}&map=ft",
     "card": "section[class*='product'], article", "preco": None},
    {"nome": "Panvel", "url": f"https://www.panvel.com/panvel/buscarProduto.do?termoPesquisa={Q}",
     "card": "[class*='product-item'], article", "preco": None},
    {"nome": "Drogaria São Paulo", "url": f"https://www.drogariasaopaulo.com.br/{Q}?_q={Q}&map=ft",
     "card": "section[class*='product'], article", "preco": None},
]

PRECO_RE = re.compile(r"R\$\s*([\d\.]+,\d{2})")

def para_float(txt):
    return float(txt.replace(".", "").replace(",", "."))

def buscar(page, loja, idx):
    page.goto(loja["url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)  # deixa o JS carregar os produtos
    os.makedirs("debug", exist_ok=True)
    open(f"debug/{idx}_{loja['nome']}.html", "w", encoding="utf-8").write(page.content())

    resultados = []
    for card in page.query_selector_all(loja["card"])[:5]:
        texto = card.inner_text()
        m = PRECO_RE.search(texto)
        if m:
            nome = texto.strip().split("\n")[0][:70]
            resultados.append((nome, para_float(m.group(1))))
    return resultados

linhas, melhores = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    for i, loja in enumerate(FARMACIAS):
        ctx = browser.new_context(
            locale="pt-BR", timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )
        page = ctx.new_page()
        try:
            res = buscar(page, loja, i)
            if res:
                nome, preco = min(res, key=lambda r: r[1])
                melhores.append((preco, loja["nome"], nome))
            else:
                linhas.append(f"⚠️ {loja['nome']}: nenhum preço encontrado")
        except Exception as e:
            linhas.append(f"❌ {loja['nome']}: {type(e).__name__}")
        finally:
            ctx.close()
    browser.close()

melhores.sort()
msg = [f"💊 *{PRODUTO}*", ""]
for preco, loja, nome in melhores:
    msg.append(f"🏷 {loja}: R$ {preco:.2f}".replace(".", ",") + f"\n    {nome}")
msg += [""] + linhas

requests.post(
    f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
    json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": "\n".join(msg), "parse_mode": "Markdown"},
    timeout=30,
)
