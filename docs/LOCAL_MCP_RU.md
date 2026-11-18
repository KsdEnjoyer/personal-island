# Свой локальный MCP-сервер

MCP подключает инструменты к AI-клиенту. Здесь это отдельный Rust-процесс,
работающий с той же SQLite-базой задач, что и островок. Сервер сам не вызывает
языковые модели и не требует OpenAI API-ключа. Тариф выбранного клиента —
отдельный вопрос.

## 1. Сборка

Установи Rust stable; на Windows нужен MSVC toolchain и C++ Build Tools.
В корне репозитория:

```powershell
cargo build --locked --release -p task-mcp
```

На Windows получится `target/release/task-mcp.exe`. stdio-сервер можно собирать
и на Linux/macOS как `target/release/task-mcp`, отдельно от Windows-приложения.
У него нет сетевого listener или собственного интерфейса.

## 2. Подключение клиента

Обобщённый пример для клиентов с JSON-настройкой `mcpServers`:

```json
{
  "mcpServers": {
    "personal-island": {
      "command": "C:/path/to/personal-island/target/release/task-mcp.exe",
      "args": [],
      "env": { "PERSONAL_ISLAND_TIMEZONE": "Europe/Moscow" }
    }
  }
}
```

Замени путь на абсолютный. В JSON не нужны дополнительные shell-кавычки
вокруг пути с пробелами. Расположение файла зависит от клиента; этот JSON
нельзя напрямую вставлять в конфигурацию TOML. Перезапусти клиент.

Для Codex CLI из PowerShell:

```powershell
$mcpBinary = (Resolve-Path .\target\release\task-mcp.exe).Path
codex mcp add personal-island -- $mcpBinary
codex mcp list
```

Есть helper `scripts/register-codex.ps1`. Для явной настройки Codex используй
`~/.codex/config.toml`:

```toml
[mcp_servers.personal-island]
command = "C:/path/to/personal-island/target/release/task-mcp.exe"
default_tools_approval_mode = "writes"

[mcp_servers.personal-island.env]
PERSONAL_ISLAND_TIMEZONE = "Europe/Moscow"
# Необязательно; один путь нужно задать также приложению:
# PERSONAL_ISLAND_DB = "C:/path/to/private-data/tasks.sqlite3"
```

Переменные в открытом терминале не меняют окружение уже запущенного GUI.
stdio-процесс запускает клиент. При ручном запуске в терминале ожидание ввода
нормально: не вводи туда обычный текст.

Параметр Codex `default_tools_approval_mode = "writes"` запрашивает подтверждение
для инструментов, не помеченных read-only. Для старой версии клиента проверь
доступные параметры в [официальной инструкции](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

У stdio нет отдельного пароля: граница доверия — учётная запись ОС и запускающий
MCP-клиент. Сервер даёт и чтение, и запись задач. Включи подтверждение изменений
в клиенте. Не запускай неизвестный MCP-бинарник от администратора.

## 3. Проверка

Сначала попроси клиента показать время и список задач через Personal Island.
Для проверки записи без доступа к личному расписанию задай в конфигурации
MCP отдельный `PERSONAL_ISLAND_DB`, например:

```json
"env": {
  "PERSONAL_ISLAND_DB": "C:/path/to/test-island/tasks.sqlite3",
  "PERSONAL_ISLAND_TIMEZONE": "Europe/Moscow"
}
```

Тестовые задачи появятся в основном островке только если он использует тот же
путь. Для обычной работы убери переопределение с обеих сторон: Windows
использует `%LOCALAPPDATA%\PersonalIsland\tasks.sqlite3`.
Каталог базы должен быть доступен только нужной учётной записи.

## Инструменты

| Инструмент | Действие |
| --- | --- |
| `get_current_time` | Время IANA-зоны и UTC |
| `list_tasks`, `get_task` | Список и чтение по ID |
| `list_schedule` | Дедлайны в `[start_at, end_at)`, до 93 дней |
| `create_task` | Создать задачу |
| `create_tasks` | Атомарно создать до 50 задач |
| `update_task` | Изменить название, заметки, приоритет |
| `reschedule_task` | Перенести дедлайн и напоминание |
| `complete_task`, `reopen_task` | Завершить или вернуть задачу |
| `delete_task` | Удалить по явному запросу пользователя |

`due_at` — дедлайн, а не встреча с длительностью. Даты — RFC3339 с явным
смещением, например `2030-01-02T16:00:00+03:00`. Без отдельного
`reminder_at` напоминание назначается за 30 минут. Для «завтра» и «сегодня»
клиент сначала вызывает `get_current_time`.

Для повторов создания используй прежний `request_key`; для другого намерения
нужен новый. Для `create_tasks` ключ обязателен, для `create_task` обязателен
по HTTP и рекомендуется по stdio. Повтор с другими данными отклоняется.
Правки не затираются, удалённые задачи не восстанавливаются.

## Необязательный loopback HTTP

Нужен только клиентам, которым недостаточно stdio:

```powershell
.\scripts\start-mcp-http.ps1 -Build
```

Helper создаёт случайный bearer-токен в ACL-защищённом файле
`%LOCALAPPDATA%\PersonalIsland\mcp-bridge.token`, запускает мост без видимого
окна и проверяет `/health`. MCP URL: `http://127.0.0.1:18741/mcp`.
Токен не печатается. В клиенте используй защищённое хранилище секретов,
не репозиторий и не чат.

Ручной запуск с уже созданным файлом:

```powershell
cargo build --locked --release -p task-mcp --features http --bins
$env:PERSONAL_ISLAND_MCP_BIND = '127.0.0.1:18741'
$env:PERSONAL_ISLAND_MCP_TOKEN_FILE = "$env:LOCALAPPDATA\PersonalIsland\mcp-bridge.token"
.\target\release\task-mcp-http.exe
```

Остановка фонового моста: `scripts/stop-mcp-http.ps1`.
Не задавай одновременно TOKEN и TOKEN_FILE. Мост требует токен на всех
маршрутах, отвергает browser Origin и внешний bind. Не пробрасывай порт
напрямую в интернет. [Для веб-ChatGPT используется OAuth](CHATGPT_MCP_RU.md).

## Диагностика

- Нет инструментов: проверь путь/ошибку запуска и перезапусти клиент.
- Нет задачи в UI: сравни базы и окружение обоих процессов.
- Неверное время: задай IANA-зону в MCP; UI использует часовой пояс Windows.
- HTTP 401: проверь токен и нужный процесс моста.
- HTTP 403 из браузера: browser Origin намеренно запрещён.
- Порт занят: выбери другой loopback-порт, не завершай чужие процессы.
- В отчёт об ошибке не прикладывай личную базу, Authorization, токены и задачи.
