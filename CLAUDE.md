# CLAUDE.md — Orbika (bitácora del proyecto)

> Instrucciones y contexto para Claude Code / Gemini CLI al trabajar en este proyecto.
> **Si es tu primera vez aquí, lee `.ai-context/README.md` — te ahorra explorar y gastar tokens.**

## Qué es esto
**Orbika** = consola de cotización de repuestos para el negocio **autolujoslaser** (Colombia). Recibe correos de la aseguradora **SURA**, extrae repuestos, los cruza contra 32 proveedores (~35.5k productos) + búsqueda web, prioriza con IA (Gemini) y lo muestra en una web. Corre en ESTE portátil Debian como servidor 24/7.

## Dónde está todo
- **Código fuente:** `~/desarrollos/orbika/` (este dir).
- **Stack corriendo:** `~/desarrollos/orbika-runtime/docker-compose.yml` (7 contenedores).
- **Secretos:** `~/desarrollos/orbika-runtime/secrets/` (SURA, Gmail, Gemini key — chmod 600).
- **Instalador cliente (.exe):** `~/desarrollos/orbika-installer/Orbika-Setup.exe`.
- **Backups DB:** `~/backups/` (cron diario 3AM).
- **Documentación:** `docs/` (manual usuario, técnico, auditoría) y `.ai-context/` (para IA).
- **Automatización:** `skills/` (verificar, backup, reprocesar, rebuild, screenshot).

## ⚠️ REGLAS DE ORO (no las rompas)
1. **Editar código ≠ desplegar.** El stack corre con IMÁGENES. Tras editar `tools/*.py` o `apps/**`, hay que `cd ~/desarrollos/orbika-runtime && docker compose build <servicio> && docker compose up -d <servicio>`. Servicios: `orbika-web` (TSX), `orbika-api`/`orbika-runner` (Python).
2. **La web es PWA** → tras rebuild, el cliente debe hacer Ctrl+Shift+R.
3. **`supplier_catalog/` NO está en las imágenes** — se monta por volumen al runner. No lo borres.
4. **Antes de un cambio grande, lee `.ai-context/03-GOTCHAS.md`** — casi todo lo que puede fallar ya falló y está documentado (NTFS dirty, token_set con int, fechas en JSON, OOM, DNS en build, WiFi inestable, etc.).
5. **Cuidado con el postgres:** `docker exec orbika-postgres psql` desde el server de la AGENCIA (192.168.1.75) NO es la DB de Orbika; la real está en el portátil.

## Verificación rápida (30s)
```bash
bash ~/desarrollos/orbika/skills/verificar.sh    # o:
cd ~/desarrollos/orbika-runtime && docker compose ps
curl -s -o /dev/null -w "web %{http_code}\n" http://127.0.0.1/
```

## Historial / memoria
Todo el proceso de construcción está en la memoria de Claude Code:
`~/.claude/projects/-home-agoraelectoral/memory/project_portatil_debian_dev.md` (cronológico, detallado).

## Estado (2026-07-17)
✅ Stack completo, scraping SURA 24/7, búsqueda web (SearXNG)+caché(Redis)+grafo, IA Gemini, frontend con badges/botones/actividad, instalador seguro con Tailscale, backup automático diario, docs+skills.
⚠️ Pendiente: WiFi inestable (cable), monitoreo/alertas, precio real ML (OAuth), firmar .exe, filtrar display a solo proveedores conocidos. Detalle en `docs/AUDITORIA-PRODUCCION.md` y `.ai-context/05-ESTADO.md`.

## Convenciones
- Español colombiano en la UI y mensajes.
- No subir `secrets/`, `.env`, ni la key de Gemini a repos.
- Preferir editar y RECONSTRUIR (no `docker cp` salvo pruebas rápidas).
