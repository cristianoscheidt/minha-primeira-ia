            f"Preço normal: {brl(promo['regular_unit_price'])} por unidade." if promo["regular_unit_price"] else "Preço normal: não identificado.",
            f"Total de {promo['minimum_quantity']} unidades: {brl(promo['promo_total'])}.",
        ])
        if promo["savings"] is not None:
            lines.append(f"Economia na quantidade mínima: {brl(promo['savings'])}.")
    elif item.get("list_price") and item["list_price"] > item["price"]:
        lines.append(f"Preço anterior/listado: {brl(item['list_price'])}.")
    if item.get("available") is not None:
        lines.append(f"Disponibilidade informada pela página: {item['available']}.")
    return "\n".join(lines)


def telegram_send(message):
    # Mantém o nome de Secret que o usuário já utiliza em outros projetos.
    token = os.getenv("TELEGRAM_TOKEN", "").strip() or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        missing = []
        if not token:
            missing.append("TELEGRAM_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        raise RuntimeError("Secrets ausentes no ambiente do workflow: " + ", ".join(missing))

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    # Telegram limita texto a 4096 caracteres; envia em partes sem cortar palavras.
    chunks = []
    remaining = message
    while remaining:
        if len(remaining) <= 3900:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, 3900)
        if cut < 1000:
            cut = 3900
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    for chunk in chunks:
        response = requests.post(
            endpoint,
            data={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError("Telegram recusou a mensagem: " + str(payload.get("description", "erro desconhecido")))


def main():
    query = " ".join(sys.argv[1:]).strip() or os.getenv("PRODUCT", "").strip()
    if not query:
        raise SystemExit("Informe o produto no campo produto do GitHub Actions.")

    session = requests.Session()
    session.headers.update(HEADERS)
    all_results = []
    store_status = {}

    for store, config in FARMACIAS.items():
        print(f"Consultando {store}...")
        try:
            results, error = search_store(session, store, config, query)
            all_results.extend(results)
            store_status[store] = f"{len(results)} produto(s)" if results else (error or "sem resultado")
        except Exception as exc:  # registra falha de uma loja sem abortar as outras
            store_status[store] = f"falha: {exc.__class__.__name__}"
        time.sleep(0.7)

    # Deduplica URL e título. Não escolhe silenciosamente um produto de outra gramatura.
    unique = {}
    for item in all_results:
        key = (item["store"], item["url"], item["title"].lower())
        unique[key] = item
    all_results = list(unique.values())
    all_results.sort(key=lambda x: x["price"])

    lines = [
        "🔎 COMPARADOR DE FARMÁCIAS",
        f"Pesquisa: {query}",
        "Região de referência: Balneário Camboriú – SC",
        "Consulta: catálogo/site público; retirada em loja não confirmada automaticamente.",
        "",
    ]

    if all_results:
        lines.append("RESULTADOS COM PREÇO IDENTIFICADO")
        for item in all_results[:20]:
            lines.extend(["", format_product(item)])
        lines.extend(["", "Menor preço unitário encontrado:", f"{brl(all_results[0]['price'])} – {all_results[0]['store']}."])
    else:
        lines.append("Não foi possível identificar preços automaticamente nesta consulta.")

    lines.extend(["", "STATUS POR FARMÁCIA"])
    for store, status in store_status.items():
        lines.append(f"• {store}: {status}")

    lines.extend([
        "",
        "Observação: preço promocional por quantidade só é exibido quando a condição e a quantidade mínima aparecem explicitamente nos dados da página. Confirme preço final e estoque para retirada no aplicativo/site antes de ir à loja.",
    ])
    message = "\n".join(lines)
    print(message)
    telegram_send(message)


if __name__ == "__main__":
    main()
