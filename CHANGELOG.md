# Changelog

All notable changes are documented here. The file is maintained by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commits](https://www.conventionalcommits.org/); versions follow [SemVer](https://semver.org/).

## [0.1.1](https://github.com/Filpin011/ha-wallbox-web/compare/v0.1.0...v0.1.1) (2026-11-10)


### Bug Fixes

* hassfest URL placeholder in config flow; no real socket in connection-error test ([e858d85](https://github.com/Filpin011/ha-wallbox-web/commit/e858d850e8df4e7478b1554ecaec697395062430))

## 0.1.0 (unreleased)

### Features

- First version: config flow (URL + API token, reauth, reconfigure), Supervisor discovery of the Wallbox WEB add-on,
  one device per station, sensors / binary sensors / buttons / number / select, Energy dashboard lifetime energy,
  push updates over server-sent events with 30 s polling fallback, diagnostics, websocket command for the card.
