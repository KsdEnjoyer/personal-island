#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -f apps/desktop/package-lock.json || ! -f scripts/create-desktop-shortcut.sh ]]; then
    printf 'Запусти установщик из полной копии репозитория Personal Island.\n' >&2
    exit 1
fi
if ! command -v apt-get >/dev/null; then
    printf 'Этот установщик требует APT. Для Arch и Manjaro используй install-linux-pacman.sh.\n' >&2
    exit 1
fi
if (( EUID == 0 )); then
    printf 'Запусти установщик от обычного пользователя. Для APT он вызовет sudo.\n' >&2
    exit 1
fi

printf '[1/3] Установка системных пакетов\n'
sudo apt-get update
if ! apt-cache show libwebkit2gtk-4.1-dev >/dev/null 2>&1 || ! apt-cache show playerctl >/dev/null 2>&1; then
    . /etc/os-release
    if [[ ${ID:-} == ubuntu || " ${ID_LIKE:-} " == *' ubuntu '* ]]; then
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y -n universe
        sudo apt-get update
    fi
fi
sudo apt-get install -y \
    git build-essential pkg-config curl ca-certificates file \
    libgtk-3-dev libwebkit2gtk-4.1-dev libssl-dev \
    libayatana-appindicator3-dev librsvg2-dev libxdo-dev \
    playerctl pulseaudio-utils libglib2.0-bin xdg-utils wl-clipboard xclip

printf '[2/3] Подготовка Node.js и Rust и сборка Personal Island\n'
if ! command -v npm >/dev/null || ! node -e '
    const [major, minor] = process.versions.node.split(".").map(Number);
    process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1);
' 2>/dev/null; then
    export NVM_DIR="${NVM_DIR:-${XDG_CONFIG_HOME:+$XDG_CONFIG_HOME/nvm}}"
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
        mkdir -p -- "$NVM_DIR"
        curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.41.0/install.sh \
            | PROFILE=/dev/null bash
    fi
    set +u
    . "$NVM_DIR/nvm.sh" --no-use
    nvm use 24 || nvm install 24
    set -u
fi

export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
if command -v rustup >/dev/null; then
    rustup toolchain install stable --profile minimal
else
    curl --proto '=https' --tlsv1.2 -fsS https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable --no-modify-path
fi
npm --prefix apps/desktop ci
CARGO_TARGET_DIR="$PWD/target" npm --prefix apps/desktop run tauri -- build --no-bundle -- --locked

printf '[3/3] Установка приложения и создание ярлыка\n'
bash scripts/create-desktop-shortcut.sh --install
printf 'Готово. Открой Personal Island из меню приложений.\n'
