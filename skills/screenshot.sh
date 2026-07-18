#!/usr/bin/env bash
# Captura de la UI usando el Chromium del runner (no hay MCP de navegador).
# Uso: ./screenshot.sh [quote_key]   -> deja /tmp/orbika-ui.png en el portátil
set -u
QK="${1:-}"
IP="$(hostname -I | awk '{print $1}')"
cat > /tmp/_shot.py <<PY
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox"])
    pg=b.new_context(viewport={"width":1680,"height":1000}).new_page()
    pg.goto("http://${IP}/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(5500)
    qk="${QK}"
    if qk:
        try:
            pg.locator("button.tab", has_text="Todas").click(); pg.wait_for_timeout(700)
            pg.locator("input[placeholder*='Buscar']").fill(qk); pg.wait_for_timeout(1800)
            pg.locator("div.qrow").first.click(); pg.wait_for_timeout(3000)
        except Exception as e: print("nav:",e)
    pg.screenshot(path="/data/ui.png"); print("ok"); b.close()
PY
docker cp /tmp/_shot.py orbika-runner:/tmp/_shot.py >/dev/null 2>&1
docker exec orbika-runner python3 /tmp/_shot.py
docker cp orbika-runner:/data/ui.png /tmp/orbika-ui.png >/dev/null 2>&1
echo "captura en /tmp/orbika-ui.png ($(du -h /tmp/orbika-ui.png 2>/dev/null | cut -f1))"
