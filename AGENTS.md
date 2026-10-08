# Agent instructions

Read [DEV.md](DEV.md) before changing code, then the relevant section of
[docs/spec.md](docs/spec.md) and [docs/design.md](docs/design.md).

## Working boundaries

- This is a local Python + POSIX shell project. Work from the repository root;
  there is no Python package installation step for this project's own source.
- Use `sh scripts/offline-check.sh` for normal verification. It uses synthetic
  fixtures and fake device commands; no CodexBar, Docker, or Kindle is required.
- Treat `.env`, `runtime/`, `build/`, and `docs/local/` as private local state.
  Do not include their contents in commits, screenshots, logs, or PR descriptions.
- Never read or copy provider auth files, cookies, Keychain data, or raw CLI
  payloads to debug this project. The collector delegates authentication to
  CodexBar and writes only the standard allowlisted snapshot.
- Use the generic `config/providers.json` and configuration examples as the
  public defaults. Personal paths, hosts, IP addresses, and secrets belong in
  ignored local configuration or generated bundles.
- Real account collection, LAN publication, launchd installation, USB writes,
  and Kindle RTC/power operations need authorization in the current task.
  Do not infer authorization from an archived log or an example command.
- Preserve existing user data and services. A generated bundle is not a live
  deployment. Changing local source does not update the installed Kindle.
- Report synthetic tests, host HTTP checks, device self-reports, and physical
  visual acceptance separately. Do not claim hardware validation from mocks.
- Update README/spec/runbook when a change affects setup, contracts, or behavior.

## Code navigation

If a `.codegraph/` directory exists, use CodeGraph before text search to locate
or understand code. Otherwise use `rg`; do not create an index automatically.
