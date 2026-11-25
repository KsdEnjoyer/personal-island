# Codex instructions for Personal Island

This is a personal tasks desktop application for Windows 10/11 and Linux, built with Rust + Tauri 2 + Svelte.

## Workspace
- `crates/task-core`: shared task and SQLite logic (single source of truth).
- `crates/task-mcp`: Rust stdio MCP tools called by Codex.
- `apps/desktop/src-tauri`: Tauri Rust host and island reminder scheduler.
- `apps/desktop/src`: Svelte frontend.

## Behaviors
- When the user explicitly asks to create or update personal tasks, prefer the `personal-island` MCP server tools over editing SQLite manually.
- For relative dates (e.g. "tomorrow") call `get_current_time` first and use the user's local timezone in an explicit RFC3339 timestamp.
- Confirm task creation using tool results; don't claim a task was saved unless the MCP tool returned success.
- Avoid creating duplicates; inspect existing tasks when the request might refer to an existing one.
- Never silently delete or complete tasks without an explicit request.
- All data stays local by default. Do not add public HTTP endpoints without authentication and the user's request.

## Development
- Keep proposed changes local for the user's review. Do not commit or push them to the public repository until the user explicitly accepts the changes and authorizes publication.
- Run `cargo test -p task-core` and `cargo check -p task-mcp` for Rust changes.
- Build Svelte using `npm run build` from `apps/desktop`.
- On Windows run Tauri with `npm run tauri dev` from `apps/desktop`.
- On Linux run Tauri with `npm run tauri -- dev` from `apps/desktop`.
