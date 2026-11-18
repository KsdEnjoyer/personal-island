# Веб-ChatGPT и свой HTTPS/OAuth-шлюз

Сначала настрой [локальный MCP](LOCAL_MCP_RU.md). Для stdio-клиента VPS не нужен.
Здесь описан дополнительный вариант удалённого URL. Доступность пользовательских
MCP зависит от аккаунта/workspace: сверяй шаги с
[официальной документацией OpenAI](https://developers.openai.com/plugins/deploy/connect-chatgpt).

## Схема

```text
ChatGPT → HTTPS/OAuth → твой Nginx → gateway 127.0.0.1:18740
                                        ↓
                         reverse SSH 127.0.0.1:18741 → ПК
                                        ↓
                         task-mcp-http → локальная SQLite
```

Нужны работающий ПК, свой Linux VPS, домен с HTTPS, OpenSSH и Python 3.10+.
Общего сервера проекта нет. Шлюз не вызывает модели и не требует OpenAI API-ключа;
VPS, домен и клиент могут иметь свою стоимость.

Это схема **одного владельца**, не многопользовательский сервис. Данные задач
проходят через VPS в запросах/ответах. Он не хранит копию календаря, но VPS и его
администратор входят в границу доверия и могут обращаться к локальному мосту.

## Собственная установка

1. Настрой свой HTTPS-хост, например `island.example.com`. Все адреса здесь
   нужно заменить. Сохрани конфиги Nginx/SSH перед изменениями.
2. На ПК: `scripts/start-mcp-http.ps1 -Build`. Не открывай 18741 снаружи.
3. Создай защищённый пароль и настрой локальный relay-конфиг:

   ```powershell
   .\scripts\prepare-waicore-mcp.ps1 -PublicBase 'https://island.example.com/island-mcp'
   $relayDir = Join-Path $env:LOCALAPPDATA 'PersonalIsland\waicore-mcp'
   Copy-Item .\examples\relay.example.json (Join-Path $relayDir 'relay.json')
   notepad (Join-Path $relayDir 'relay.json')
   ```

   Укажи свои SSH-хост, пользователя, пути ключей, HTTPS-адрес и отдельный
   административный SSH-доступ. Исторические имена каталога/скриптов не
   привязывают к провайдеру. Существующий `owner.json` не перезаписывается.
4. Проверь fingerprint хоста независимым каналом и добавь верный ключ в
   `known_hosts`. Не отключай `StrictHostKeyChecking`.
5. Для подготовленного Debian/Ubuntu VPS есть необязательный helper:

   ```powershell
   python -m venv .venv-mcp-gateway
   .\.venv-mcp-gateway\Scripts\python.exe -m pip install -r services/mcp-gateway/requirements.txt
   .\.venv-mcp-gateway\Scripts\python.exe services/mcp-gateway/deploy.py --run
   ```

   Сначала прочитай оба deployment-скрипта: они создают системных пользователей,
   службу, каталоги и ограничения SSH. Требуется собственный admin SSH с
   `sudo -n`. Helper не редактирует существующий virtual host Nginx.
6. Внутри собственного HTTPS `server { ... }` на VPS добавь:

   ```nginx
   include /etc/nginx/snippets/personal-island-mcp.conf;
   ```

   Выполни `sudo nginx -t`, затем `sudo systemctl reload nginx`. Не записывай
   query string OAuth-маршрутов в access log. Gunicorn должен иметь один worker,
   как в созданном unit: блокировки обмена/ротации рассчитаны на один процесс.
7. На Windows: `scripts/install-waicore-mcp-autostart.ps1`. Он читает
   `relay.json`; `PERSONAL_ISLAND_RELAY_CONFIG` выбирает другой файл.
   По умолчанию helper использует `target/debug/task-mcp-http.exe`.

Для диагностики живого сервера есть `scripts/audit-waicore-mcp.py` и
`scripts/check-waicore-mcp.py`. Они не входят в CI. Правки опубликованной
копии кода не обновляют уже запущенную службу VPS: её нужно обновлять отдельно.

## Подключение ChatGPT

В интерфейсе пользовательских MCP/плагинов укажи свой URL
`https://island.example.com/island-mcp/mcp` и OAuth. Шлюз поддерживает DCR,
PKCE S256 и строгие callback URI ChatGPT. При выборе CIMD/DCR используй DCR;
Client Secret для публичного DCR-клиента не нужен.

`scripts/show-waicore-mcp.ps1` показывает локальное окно пароля. Введи пароль
только на собственной HTTPS-странице шлюза, не в чате.
`tasks:read` — чтение; `tasks:write` — создание, изменение, завершение и
удаление задач. Расширение прав требует нового согласия. Сначала проверь
`get_current_time` и чтение расписания, затем явно запрошенную запись.

При `insufficient_scope` переподключи клиент с нужными правами. При 403 на старой
форме начни OAuth заново. При выключенном ПК/relay получишь
`503 island_offline`. Шлюз не повторяет записи автоматически: клиент повторяет
создание с тем же `request_key`.

## Секреты

- Windows `owner.json` содержит пароль открытым текстом под ACL владельца и
  SYSTEM. Это не шифрование. Файлы не должны попадать в Git или облачный backup.
- VPS хранит scrypt-хеш пароля и хеши кодов/токенов; сессионный ключ и отдельный
  bridge-токен остаются секретами сервера.
- Access token — 10 минут; refresh — до 30 дней, с ротацией и отзывом семейства
  при повторном использовании старого refresh token.
- Relay-ключ имеет только reverse-forward одного loopback-порта; admin-ключ —
  отдельный. Ключи, пароль и токены не передаются через argv или логи.
- Остановка: `scripts/stop-waicore-mcp.ps1`; флаг `-DisableAutostart` отключает
  задачу Windows. Тест восстановления намеренно прерывает соединение:
  запускай `scripts/qa-mcp-recovery.py` отдельно от активных запросов.

[Политика безопасности](../SECURITY.md).
[Требования OAuth OpenAI](https://developers.openai.com/plugins/build/auth).
