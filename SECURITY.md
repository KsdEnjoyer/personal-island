# Security policy

This is an early-stage, single-owner Windows application. Only the current
main branch is maintained; no independent penetration test or security
certification has been performed. See [the dated review](docs/SECURITY_REVIEW.md)
for checks actually run and remaining dependency findings.

## Report a vulnerability

Use the repository's **Security → Report a vulnerability** once the maintainer
has enabled private vulnerability reporting on GitHub. If it is unavailable,
open a minimal issue requesting a private contact channel; do not publish
credentials, task databases, clipboard content or exploit details in an issue.
Do not test another user's MCP endpoint or infrastructure without permission.

## Trust boundaries

- The desktop runs with the user's Windows permissions. It includes a global
  hotkey, explicit clipboard-paste automation and media controls. A malicious
  local process running as that same user is outside its isolation guarantees.
- Databases are not encrypted by the application. Protect the OS account,
  disk, backups and private directories. Clipboard recording is opt-in on a
  fresh installation; pausing does not remove old entries. Password-manager
  exclusion markers are respected, but arbitrary secrets cannot be detected.
- Audio analysis captures the default Windows output mix only while needed.
  It does not open a microphone or persist PCM. Weather requests reach
  Open-Meteo. The app does not include telemetry or an LLM service.
- Local stdio MCP grants the launching client access to task tools, including
  write/delete. Client approval policies are essential; tool annotations are
  hints, not server-side authorization. Task text is untrusted data, never
  instructions. The MCP server exposes tasks, not clipboard/notes/audio/files.
- Private HTTP requires a strong bearer token, loopback binding and accepts
  no browser Origin. Never publish that listener or the Vite development server.
- The optional OAuth gateway is a trusted, single-owner component. It sees task
  traffic and holds a bridge credential. Scopes distinguish read and write;
  write includes deletion. It is not a tenant-isolated SaaS service. HTTPS,
  a restricted SSH relay and a secured VPS are required. Run one gateway
  worker as documented; token rotation is serialized within that worker.

## Secrets and logs

Generate different secrets for OAuth sessions, the owner password and the
private bridge. Use token files with restrictive permissions, not argv or
committed environment files. Windows relay credentials are stored outside the
checkout under an owner/SYSTEM ACL; the local owner password is plaintext in
that protected file. The VPS stores a password hash and hashes of OAuth tokens,
but still holds plaintext session/bridge secrets. Rotate leaked secrets and
revoke OAuth token families; deleting a Git file is not sufficient.

Never attach real SQLite files, WebView profiles, screenshots of personal data,
HTTP bodies, OAuth query strings, Authorization headers or private keys to
issues/CI artifacts. A .gitignore is a convenience, not a security boundary.

## Maintainer checks

1. Run `python scripts/audit-release.py` and Gitleaks against the publication
   snapshot; scan Git history as well before pushing an existing repository.
2. Run Rust, frontend and OAuth tests, including HTTP auth/origin/body limits.
3. Run `cargo audit`, `python scripts/audit-npm.py` and `pip-audit` for the
   gateway. Read warnings and known exceptions; do not silently suppress them.
4. Keep CI permissions read-only and actions pinned. Do not run untrusted pull
   request code with deployment credentials or `pull_request_target`.
5. Enable GitHub secret scanning/push protection, private vulnerability reports,
   dependency alerts and branch protection when creating the repository.
6. Deploy updated gateway dependencies separately from desktop/source releases.

Protocol references: [MCP transport security](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[MCP security practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices),
[Tauri capabilities](https://v2.tauri.app/security/capabilities/).
