#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -f apps/desktop/package-lock.json || ! -f scripts/create-desktop-shortcut.sh ]]; then
    printf 'Запусти установщик из полной копии репозитория Personal Island.\n' >&2
    exit 1
fi
if ! command -v pacman >/dev/null; then
    printf 'Этот установщик требует Pacman. Для Debian и Ubuntu используй install-linux-apt.sh.\n' >&2
    exit 1
fi
if (( EUID == 0 )); then
    printf 'Запусти установщик от обычного пользователя. Для Pacman он вызовет sudo.\n' >&2
    exit 1
fi

export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
packages=(
    git base-devel pkgconf curl ca-certificates file nodejs npm
    gtk3 webkit2gtk-4.1 openssl librsvg libayatana-appindicator
    playerctl libpulse glib2 xdg-utils wl-clipboard xclip
)
if ! command -v cargo >/dev/null || ! command -v rustc >/dev/null; then
    packages+=(rustup)
fi

printf '[1/3] Установка системных пакетов\n'
sudo pacman -Syu --needed "${packages[@]}"

printf '[2/3] Подготовка Rust и сборка Personal Island\n'
if command -v rustup >/dev/null; then
    rustup toolchain install stable --profile minimal
fi
npm --prefix apps/desktop ci
CARGO_TARGET_DIR="$PWD/target" npm --prefix apps/desktop run tauri -- build --no-bundle -- --locked

printf '[3/3] Установка приложения и создание ярлыка\n'
bash scripts/create-desktop-shortcut.sh --install
printf 'Готово. Открой Personal Island из меню приложений.\n'
