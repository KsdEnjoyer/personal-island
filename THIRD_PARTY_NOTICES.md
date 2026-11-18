# Third-party components and branding

The repository's code is MIT-licensed. Dependencies retain their own licenses;
the root Cargo.lock and apps/desktop/package-lock.json record exact versions.
Consult each dependency's LICENSE/NOTICE when redistributing binaries, including
transitive crates, npm packages and the optional Python gateway stack.

Major components include Tauri, Svelte, Tokio, SQLx, rmcp, Lucide icons, Tiptap,
Flask, Werkzeug, OAuthLib and Requests. No external fonts are bundled; Windows
system fonts are selected by name. Windows/WebView2 and music applications are
separate products and are not relicensed by this repository.

Weather is supplied by [Open-Meteo](https://open-meteo.com/); preserve attribution
and follow the provider's data/service terms. Album artwork and task/clipboard
content are runtime user data, not sample assets distributed under MIT.

The vector mask is authored as repository SVG code. Character-inspired theme
names and references do not grant rights to third-party characters, trademarks
or logos. Review such references before marketing a public binary. Personal
Island is an independent project; no affiliation with OpenAI, Yandex, Windows,
Cyberpunk or the design-reference applications is claimed.
