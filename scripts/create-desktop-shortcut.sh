#!/usr/bin/env bash
set -euo pipefail

install_copy=false
if [[ ${1:-} == --install && $# == 1 ]]; then
    install_copy=true
    shift
fi
if (( $# > 2 )) || [[ ${1:-} == --install || ( $# == 2 && $2 != --appimage-extract-and-run ) ]]; then
    printf 'Использование: %s [--install | исполняемый файл [--appimage-extract-and-run]]\n' "$0" >&2
    exit 2
fi

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
binary=${1:-"$root/target/release/personal-island-desktop"}
if [[ ! -f "$binary" || ! -x "$binary" ]]; then
    printf 'Исполняемый файл недоступен: %s\n' "$binary" >&2
    printf 'Собери приложение по README или передай путь к исполняемому AppImage.\n' >&2
    exit 1
fi

IFS= read -r -d '' binary < <(realpath -z -- "$binary")
icon="$root/apps/desktop/src-tauri/icons/icon.png"
data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}
if [[ "$data_dir" != /* ]]; then
    data_dir="$HOME/.local/share"
fi
if [[ "$binary$icon$data_dir" == *$'\n'* || "$binary$icon$data_dir" == *$'\r'* ]]; then
    printf 'Путь к приложению, значку или каталогу данных содержит перевод строки.\n' >&2
    exit 1
fi

if [[ $install_copy == true ]]; then
    install_dir="$data_dir/personal-island"
    mkdir -p -- "$install_dir"
    temp=$(mktemp -- "$install_dir/.personal-island.XXXXXX")
    trap 'rm -f -- "$temp"' EXIT
    install -m 755 -- "$binary" "$temp"
    install -m 644 -- "$icon" "$install_dir/icon.png"
    binary="$install_dir/personal-island-desktop"
    icon="$install_dir/icon.png"
    mv -fT -- "$temp" "$binary"
fi

applications="$data_dir/applications"
shortcut="$applications/dev.personalisland.launcher.desktop"
mkdir -p -- "$applications"

# Exec uses two layers of escaping. env keeps the path out of the executable
# position, which GLib checks before expanding literal percent signs.
exec_path=$(printf '%s' "$binary" | sed -e 's/\\/\\\\\\\\/g' -e 's/["$`]/\\\\&/g' -e 's/%/%%/g')

temp=$(mktemp -- "$applications/.personal-island.XXXXXX")
trap 'rm -f -- "$temp"' EXIT
cat > "$temp" <<EOF
[Desktop Entry]
Type=Application
Name=Personal Island
Exec=/usr/bin/env "$exec_path"${2:+ $2}
Icon=${icon//\\/\\\\}
Terminal=false
Categories=Utility;
StartupWMClass=personal-island-desktop
EOF
mv -fT -- "$temp" "$shortcut"
printf 'Ярлык добавлен в меню приложений: %s\n' "$shortcut"
