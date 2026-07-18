# Orbika Desktop Shell

This folder contains the Tauri-based desktop shell for Orbika.

## Current Status

The desktop shell is now buildable in WSL and no longer blocked by the Tauri toolchain.

Verified behavior:

- development loads the local console at `http://127.0.0.1:3000`
- production uses the exported static web assets from `apps/web/out`
- `cargo tauri build` succeeds in WSL after the bootstrap prerequisites are installed

## Requirements

Before building on WSL, make sure the host has:

- Rust toolchain with `cargo`
- Tauri CLI
- Node 22 via `nvm`
- Linux packages required by Tauri/WebKit
- a valid WSL browser/runtime environment

## Bootstrap

Use the repo bootstrap script first:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
scripts/bootstrap-wsl-tauri.sh
```

If the command is non-interactive, run it from a shell that can accept `sudo` or pre-install the required packages.

## Build And Dev Commands

Run the desktop in development:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/desktop/src-tauri
source ~/.cargo/env
cargo tauri dev
```

Build the desktop bundle:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/desktop/src-tauri
source ~/.cargo/env
cargo tauri build
```

## Notes

- The desktop shell must keep the launcher, backend, and matching flow intact.
- The web app is exported statically, so the desktop build expects `apps/web/out`.
- The Tauri icon lives in `apps/desktop/src-tauri/icons/icon.png` and must remain RGBA-safe.
