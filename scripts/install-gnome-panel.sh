#!/usr/bin/env bash
set -euo pipefail

uuid=personal-island@personalisland.dev
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bundle=$(mktemp -d)
trap 'rm -rf -- "$bundle"' EXIT

gnome-extensions pack --out-dir "$bundle" "$root/integrations/gnome-shell/$uuid"
gnome-extensions install --force "$bundle/$uuid.shell-extension.zip"
if ! gnome-extensions enable "$uuid"; then
    gjs -c '
        const {Gio} = imports.gi;
        const settings = new Gio.Settings({schema_id: "org.gnome.shell"});
        const uuid = "personal-island@personalisland.dev";
        const enabled = settings.get_strv("enabled-extensions");
        if (!enabled.includes(uuid))
            settings.set_strv("enabled-extensions", [...enabled, uuid]);
        settings.set_strv("disabled-extensions", settings.get_strv("disabled-extensions").filter(id => id !== uuid));
        Gio.Settings.sync();
    '
fi
if [[ ${XDG_SESSION_TYPE:-} == wayland ]]; then
    printf 'Если GNOME уже загружал расширение, войди в сеанс заново для применения обновления.\n'
fi
