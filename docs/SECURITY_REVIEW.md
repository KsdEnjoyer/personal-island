# Подготовка к открытому репозиторию — 2026-11-18

Это проверка исходников и зависимостей, не независимый pentest и не гарантия
отсутствия уязвимостей. Публикация на GitHub и deployment живого VPS в неё
не входят. Полные локальные отчёты лежат в игнорируемом каталоге artifacts.

## Что изменено

- Личные домен, публичный IP, административный SSH-аккаунт, ключ и имя
  виртуального хоста убраны из исходников/публичной документации. Helpers
  используют внешний relay.json. Локальные настройки существующего владельца
  сохранены вне checkout; пароли и токены при этом не читались и не менялись.
- Из Git исключены базы, WAL/SHM, видео, скриншоты, логи, окружения, ключи,
  токены и локальные конфиги. Добавлен аудит Git-кандидатов и безопасного
  publication snapshot; Gitleaks проверяет содержимое без вывода секретов.
- OAuthLib обновлена 3.3.1 → 4.0.1. Покрыты OAuth/PKCE, согласие, scopes,
  refresh-ротация, неверная конфигурация, лимиты и отсутствие auth passthrough.
- SQLx обновлена 0.8 → 0.9.1; закреплена libsqlite3-sys 0.39.1 с исправленной
  bundled SQLite. Runtime-тест проверяет, что реально загружена SQLite >=3.54.0.
  Это устраняет [RUSTSEC-2026-0459](https://rustsec.org/advisories/RUSTSEC-2026-0459.html).
- Шлюз отказывает при слабых/неверных секретах, plaintext-пароле вместо
  scrypt-хеша и URL с credentials. Redirect от внутреннего HTTP-моста не
  выполняется. Существующие Origin/CSRF/PKCE/resource/scope-проверки сохранены.
- Clipboard history в новой установке выключена до согласия. Сохранённое
  явное предпочтение не сбрасывается; отказ от записи и persistence проверены.
- Tauri разрешает только необходимые JS event listen/unlisten. Production CSP
  отделена от dev CSP: релиз не получает доступ к Vite/его WebSocket, iframe,
  object или формам. Inline style пока нужен существующим компонентам.
- Deployment-helper больше не редактирует существующий Nginx virtual host.
  Добавлены MIT, SECURITY, CONTRIBUTING, инструкции MCP и GitHub CI/Dependabot.
  Actions закреплены SHA; deployment credentials им не нужны.

## Проверки и границы

| Проверка | Состояние |
| --- | --- |
| Аудит публикационных файлов | Нет найденных секретов/запрещённых runtime-файлов в проверенном snapshot |
| Gitleaks 8.30.1, официальный бинарник с проверкой checksum | Нет найденных утечек в проверенном snapshot |
| cargo audit по RustSec DB | 0 известных vulnerability advisories после обновления SQLite; предупреждения ниже |
| Проверка yanked crates | Первоначально таймауты registry; повторный advisory-аудит использовал --no-yanked |
| pip-audit gateway requirements | 0 известных уязвимостей после OAuthLib 4.0.1; отдельно проверен Linux gunicorn |
| npm audit | Одна известная unfixed dev-only проблема ниже; полный аудит не является чистым |
| Сборка и тесты | Команды указаны ниже; нативные проверки используют временную базу/профиль |

Повторяемые команды:

```powershell
cargo fmt --all -- --check
cargo test --locked -p task-core
cargo test --locked -p task-mcp --features http
cargo check --locked -p task-mcp
cargo test --locked -p personal-island-desktop --lib
npm.cmd --prefix apps/desktop run check
npm.cmd --prefix apps/desktop run build
python scripts/audit-release.py
python scripts/audit-npm.py
cargo audit --no-yanked
.\.venv-mcp-gateway\Scripts\python.exe -m pytest services/mcp-gateway -q
.\.venv-mcp-gateway\Scripts\python.exe -m pip_audit -r services/mcp-gateway/requirements.txt
```

## Известный dev-only advisory npm

[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf):
picomatch <=4.0.7, ReDoS на специально составленных extglob-шаблонах.
На дату проверки upstream не опубликовал исправление. npm показывает несколько
затронутых пакетов по одной транзитивной цепочке, включая Vite и svelte-check.

В этом проекте зависимость используется инструментами сборки/проверки, не
приложением/MCP для обработки пользовательских glob. Не запускай dev server
для недоверенных клиентов и не собирай неизвестные ветки с секретами в окружении.
Нельзя утверждать, что наличие только в devDependencies устраняет сам дефект.

scripts/audit-npm.py допускает только этот конкретный advisory и только когда
узел lockfile действительно dev-only; остальные advisories останавливают
проверку. Он печатает предупреждение, а не выдаёт полный аудит за чистый.
Dependabot и еженедельный security workflow помогают заметить исправление.

## Предупреждения RustSec

Полный граф включает предупреждения unmaintained: chrono, chrono-tz,
proc-macro-error, zbus_names, zvariant и zvariant_derive. Есть также unsound
advisory для glib в транзитивном Linux desktop-графе; поддерживаемое приложение
собирается и для Windows, и для Linux. Они не объявлены исправленными и не скрыты глобальным ignore.
Нужен дальнейший разбор и обновление/замена зависимостей по мере поддержки
upstream. Linux-сборка проверена локально, но отдельная проверка безопасности
платформенных разрешений и пакетов ещё нужна.

## Что остаётся оператору

Защитить ОС, диски, backups и VPS; настроить GitHub protection; отдельно
обновить уже развёрнутый gateway; проверить брендинг/права на персонажные
темы перед публичным бинарным релизом. Хранилище не зашифровано приложением,
шлюз не многопользовательский. Выполнение unit-тестов не означает, что CI уже
был запущен на GitHub или что инфраструктура была переустановлена.
