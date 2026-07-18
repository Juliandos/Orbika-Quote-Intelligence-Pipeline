#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '\n[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

if ! command -v apt-get >/dev/null 2>&1; then
  log "apt-get no esta disponible. Este script esta pensado para Ubuntu/Debian en WSL."
  exit 1
fi

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  log "No ejecutes este script como root. Debe correr con un usuario normal para instalar rustup en tu HOME."
  exit 1
fi

if [[ -t 0 && -t 1 ]]; then
  SUDO=(sudo)
else
  SUDO=(sudo -n)
fi

WEBKIT_PKG=""
for candidate in libwebkit2gtk-4.0-dev libwebkit2gtk-4.1-dev; do
  if apt-cache show "$candidate" >/dev/null 2>&1; then
    WEBKIT_PKG="$candidate"
    break
  fi
done

LIBSOUP_PKG=""
for candidate in libsoup2.4-dev libsoup-2.4-dev; do
  if apt-cache show "$candidate" >/dev/null 2>&1; then
    LIBSOUP_PKG="$candidate"
    break
  fi
done

JAVASCRIPTCORE_PKG=""
for candidate in libjavascriptcoregtk-4.0-dev libjavascriptcoregtk-4.1-dev; do
  if apt-cache show "$candidate" >/dev/null 2>&1; then
    JAVASCRIPTCORE_PKG="$candidate"
    break
  fi
done

TAURI_CLI_VERSION="${TAURI_CLI_VERSION:-^1}"

log "Actualizando indices de paquetes"
"${SUDO[@]}" apt-get update

log "Instalando dependencias del sistema para Tauri"
PACKAGES=(
  build-essential
  curl
  wget
  file
  libssl-dev
  libgtk-3-dev
  libayatana-appindicator3-dev
  librsvg2-dev
)

if [[ -n "$LIBSOUP_PKG" ]]; then
  PACKAGES+=("$LIBSOUP_PKG")
fi

if [[ -n "$JAVASCRIPTCORE_PKG" ]]; then
  PACKAGES+=("$JAVASCRIPTCORE_PKG")
fi

if [[ -n "$WEBKIT_PKG" ]]; then
  PACKAGES+=("$WEBKIT_PKG")
fi

"${SUDO[@]}" apt-get install -y "${PACKAGES[@]}"

log "Instalando Rust con rustup si aun no existe"
if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 https://sh.rustup.rs -sSf | sh -s -- -y
else
  log "cargo ya esta instalado; se omite rustup."
fi

if [[ -f "$HOME/.cargo/env" ]]; then
  # shellcheck disable=SC1090
  source "$HOME/.cargo/env"
fi

if ! command -v cargo >/dev/null 2>&1; then
  log "cargo no quedo disponible despues de rustup. Reabre la terminal y vuelve a ejecutar el script."
  exit 1
fi

log "Actualizando toolchain Rust"
rustup update stable

log "Instalando Tauri CLI v${TAURI_CLI_VERSION}"
if ! cargo install tauri-cli --version "${TAURI_CLI_VERSION}" --locked; then
  log "No se pudo instalar Tauri CLI con la version solicitada."
  log "Si tu proyecto sigue en Tauri v1, prueba una version 1.x explicita con:"
  log "  cargo install tauri-cli --version '^1' --locked"
  exit 1
fi

log "Verificacion final"
cargo --version
rustup --version
cargo tauri --version

log "Listo. Ahora puedes intentar:"
log "  cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/desktop/src-tauri"
log "  cargo tauri dev"
