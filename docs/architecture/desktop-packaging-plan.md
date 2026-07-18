# Desktop Packaging Plan

This document tracks the path from the Orbika web console to a packaged desktop shell.

## Goal

Turn the local Orbika console into a desktop application that can ship as a first Windows bundle without breaking:

- `tools/local_console_launcher.py`
- the FastAPI backend
- the Next.js frontend
- the DB-first matching flow

## Current Verified State

As of `2026-07-14`, the desktop path is no longer just a scaffold. It is buildable in WSL.

What is already in place:

- `apps/desktop/README.md`
- `apps/desktop/src-tauri/Cargo.toml`
- `apps/desktop/src-tauri/build.rs`
- `apps/desktop/src-tauri/tauri.conf.json`
- `apps/desktop/src-tauri/src/main.rs`
- `apps/desktop/src-tauri/icons/icon.png`
- `scripts/bootstrap-wsl-tauri.sh`

What was verified successfully in WSL:

- `scripts/bootstrap-wsl-tauri.sh` installs the Linux Tauri prerequisites and the Rust/Tauri CLI toolchain.
- `apps/web` now builds as a static export into `apps/web/out`.
- `cargo tauri build` completes successfully from `apps/desktop/src-tauri`.

## WSL Bootstrap Notes

The bootstrap script currently handles:

- Rust installation through `rustup`
- Tauri CLI installation with Cargo
- Linux dependencies required by Tauri on Ubuntu/WSL
- a non-interactive `sudo` path so automation does not hang

On Ubuntu 26.04, the working host setup needed:

- `libsoup2.4-dev`
- `libwebkit2gtk-4.1-dev`
- `libjavascriptcoregtk-4.1-dev`

The Tauri v1 build path still expects some `4.0` pkg-config and linker names. On this machine, compatibility aliases were created for:

- `javascriptcoregtk-4.0`
- `webkit2gtk-4.0`

Those aliases are host-level WSL setup, not repo code.

## Packaging Configuration

The current desktop config is intentionally simple:

- development loads the local console at `http://127.0.0.1:3000`
- production uses the exported static assets from `apps/web/out`
- Tauri uses the `custom-protocol` feature
- the build path invokes the web build before the desktop bundle is compiled

## Production Checklist

Use this checklist before calling the desktop packaging path production-ready:

- [x] `cargo tauri build` completes successfully in WSL
- [x] the web console exports to `apps/web/out`
- [x] the desktop scaffold points to the exported web assets
- [x] the bootstrap script installs Tauri prerequisites on WSL
- [x] the Tauri icon exists and is RGBA-safe
- [x] the desktop crate declares `custom-protocol`
- [x] the local launcher still starts the API and web console
- [ ] verify `cargo tauri dev` on a clean WSL session
- [ ] verify the packaged app on a clean Windows machine
- [ ] confirm WebView2 runtime availability on target Windows
- [ ] decide final installer target: `.exe`, `msi`, `nsis`, or a small bundle set
- [ ] test startup, shutdown, and relaunch behavior after packaging
- [ ] confirm the UI still loads quote list, details, supplier matches, and agentic review
- [ ] confirm DB-backed matching and internet-search fallback still work from the packaged shell
- [ ] document the release artifact location and naming convention

## Recommended Next Steps

1. Run a desktop dev session from WSL to verify the live window path:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/desktop/src-tauri
source ~/.cargo/env
cargo tauri dev
```

2. Validate the local launcher still starts the API and web console:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
PYTHONPATH=. python3 tools/local_console_launcher.py start
```

3. Smoke-test the console in the browser and in Tauri:

- quote list
- quote detail
- supplier matching
- agentic review
- internet-search matching

4. Decide the first packaging target for Windows release artifacts:

- `msi`
- `nsis`
- or a plain executable bundle for internal testing

5. After that, move into clean-machine validation and installer hardening.

## Non-Negotiables

- Keep the launcher working.
- Do not move business rules into the desktop layer.
- Keep PostgreSQL as the source of truth.
- Do not make the desktop shell depend on ad hoc local files for matching.
- Preserve a clear fallback path if the desktop bundle fails.

## Final Notes

The important milestone is already reached: the desktop shell is no longer blocked by the WSL build chain. What remains is productization:

- repeatable dev startup
- clean-machine Windows validation
- installer selection
- release hardening
