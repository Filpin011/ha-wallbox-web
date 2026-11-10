# Contributing

Thanks for helping! This is an independent, unofficial project (see [DISCLAIMER.md](DISCLAIMER.md)).

## Workflow

- `main` is protected: every change goes through a pull request with green checks (lint, tests, hassfest, HACS).
- Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
  `fix:`, `docs:`, `chore:` …, `feat!:` for breaking changes). Squash-merge, so the PR title is the commit.
- [release-please](https://github.com/googleapis/release-please) reads the commits on `main` and keeps a release PR
  open that bumps `custom_components/wallbox_web/manifest.json`, updates `CHANGELOG.md`; merging it tags `vX.Y.Z`
  and publishes the GitHub release that HACS installs.
- Pre-releases for testers: a release marked *pre-release* on GitHub is offered by HACS only to users who enable
  "Show beta versions" for this repository.

## Local setup

Dev container (VS Code / Codespaces) or a Python 3.14 virtualenv:

```sh
scripts/setup     # dependencies + pre-commit hooks
scripts/lint      # ruff format + ruff check
scripts/test      # pytest with coverage (pytest-homeassistant-custom-component)
scripts/develop   # Home Assistant on http://localhost:8123 with this integration
```

Tests run against an in-process fake of the Wallbox WEB API v1 (`tests/fake_server.py`): keep it in sync with the
API contract. Coverage must stay above 95 %.

## Guidelines

- Follow the Home Assistant [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/):
  entity names from `strings.json` (`translation_key`), unique ids, `runtime_data`, translated exceptions,
  diagnostics with redaction, `PARALLEL_UPDATES` on every platform.
- Update both `translations/en.json` and `translations/it.json` when changing `strings.json`.
- No private data in code, tests, issues or screenshots (no real URLs, IPs, serials, tokens).
