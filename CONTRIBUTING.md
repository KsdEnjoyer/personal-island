# Contributing

Use a branch and a pull request. Describe the user-visible change, its reason
and the checks run. Keep task/SQLite business logic in `crates/task-core` and
desktop/MCP adapters thin. Preserve request-key idempotency and exact-version
reminder acknowledgements. Do not silently delete or complete user tasks.

## Development

Windows and Linux desktop prerequisites and startup are in [README](README.md).
Use `npm ci`, the committed Cargo/npm lockfiles and the Rust toolchain file.
Changes to credentials, authorization, clipboard capture or native automation
need explicit tests of the denied/disabled path as well as the working path.

```powershell
cargo fmt --all -- --check
cargo test --locked -p task-core
cargo test --locked -p task-mcp --features http
npm.cmd --prefix apps/desktop run check
npm.cmd --prefix apps/desktop run build
```

On Windows and Linux also run `cargo test --locked -p personal-island-desktop --lib`.
Python gateway tests:

```powershell
python -m venv .venv-mcp-gateway
.\.venv-mcp-gateway\Scripts\python.exe -m pip install -r services/mcp-gateway/requirements.txt pytest
.\.venv-mcp-gateway\Scripts\python.exe -m pytest services/mcp-gateway/test_gateway.py -q
```

Use temporary databases/profiles for tests. The native QA scripts launch actual
Windows processes and may simulate input or clipboard operations: run only the
specific tests you understand on a suitable machine. Live relay/deployment and
recovery scripts require operator configuration and are not ordinary CI tests.
Never point write tests at a personal database or a live multi-user endpoint.

## Before sending a pull request

- Run `python scripts/audit-release.py`; inspect `git diff --cached`.
- Add no private configuration, logs, databases, recordings or credentials.
- Keep test fixtures fictional; redact local paths, task names and screenshots.
- Do not add remote endpoints, telemetry, broad Tauri permissions or arbitrary
  shell/file access without a documented requirement and security review.
- Report vulnerabilities privately following [SECURITY.md](SECURITY.md).
- Code contributions use the project's MIT license. Preserve third-party notices.
