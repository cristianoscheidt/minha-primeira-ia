import os, re, urllib.parse, requests
from playwright.sync_api import sync_playwright

PRODUTO = os.environ["PRODUTO"].strip()
Q = urllib.parse.quote(PRODUTO)

# As URLs de São João e Catarinense são tentativas (padrão de loja VTEX).
# Se falharem, a mensagem do Telegram mostra o motivo e eu ajusto.
FARMACIAS = [
    {"nome": "Drogaraia",   "url": f"https://www.drogaraia.com.br/search?w={Q}"},
    {"nome": "São João",    "url": f"https://www.saojoaofarmacias.com.br/{Q}?_q={Q}&map=ft"},
    {"nome": "Panvel",      "url": f"https://www.panvel.com/panvel/buscarProduto.do?termoPesquisa={Q}"},
    {"nome": "Catarinense", "url": f"https://www.drogariacatarinense.com.br/{Q}?_q={Q}&map=ft"},
    {"nome": "Pague Menos", "url": f"https://www.paguemenos.com.br/{Q}?_q={Q}&map=ft"},
]

PRECO_RE = re.compile(r"R\$\s*([\d\.]+,\d{2})")

# Procura blocos que tenham um link e um preço, sem depender de classe CSS
JS_CARDS = """
() => {
  const re = /R\\$\\s*[\\d\\.]+,\\d{2}/;
  const vistos = new Set(), saida = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length > 0) continue;
    if (!re.test(el.textContent || '')) continue;
    let n = el;
    for (let i = 0; i < 8 && n.parentElement; i++) {
      n = n.parentElement;
      const t = (n.innerText || '').trim();
      if (n.querySelector('a[href]') && t.length > 20 && t.length < 500) {
        if (!vistos.has(n)) { vistos.add(n); saida.push(t); }
        break;
      }
    }
  }
  return saida;
}
"""

def para_float(txt):
    return float(txt.replace(".", "").replace(",", "."))

def nome_do_card(texto):
    for linha in texto.split("\n"):
        linha = linha.strip()
        if len(linha) > 10 and "R$" not in linha:
            return linha[:70]
    return texto.split("\n")[0][:70]

def buscar(page, loja, idx):
    resp = page.goto(loja["url"], wait_until="domcontentloaded", timeout=45000)
    status = resp.status if resp else "?"
    page.wait_for_timeout(6000)
    page.mouse.wheel(0, 1500)          # rola para carregar a lista
    page.wait_for_timeout(2000)
    titulo = page.title()[:40]

    os.makedirs("debug", exist_ok=True)
    open(f"debug/{idx}_{loja['nome']}.html", "w", encoding="utf-8").write(page.content())

    palavras = [w.lower() for w in PRODUTO.split() if len(w) >= 3]
    todos, relevantes = [], []
    for texto in page.evaluate(JS_CARDS):
        m = PRECO_RE.search(texto)
        if not m:
            continue
        item = (nome_do_card(texto), para_float(m.group(1)))
        todos.append(item)
        if any(w in texto.lower() for w in palavras):
            relevantes.append(item)
    return (relevantes or todos)[:8], status, titulo

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
            res, status, titulo = buscar(page, loja, i)
            if res:
                nome, preco = min(res, key=lambda r: r[1])
                melhores.append((preco, loja["nome"], nome))
            else:
                linhas.append(f"⚠️ {loja['nome']}: sem preço (HTTP {status}, página: {titulo})")
        except Exception as e:
            linhas.append(f"❌ {loja['nome']}: {type(e).__name__}")
        finally:
            ctx.close()
    browser.close()

melhores.sort()
msg = [f"💊 {PRODUTO}", ""]
for preco, loja, nome in melhores:
    msg.append(f"🏷 {loja}: R$ {preco:.2f}".replace(".", ",") + f"\n    {nome}")
msg += [""] + linhas

requests.post(
    f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
    json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": "\n".join(msg)},
    timeout=30,
)
