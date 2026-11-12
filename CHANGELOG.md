# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-12

First public release. The application itself is unchanged; this release makes
the repository publishable and usable by people other than its author.

### Added
- MIT licence, contribution guide, security policy and code of conduct.
- English `README.md` with a complete installation guide, and an Italian
  translation in `README.it.md`.
- `docs/ARCHITECTURE.md` explaining why Samba and the web app must share one
  container, and how the persistence of `/etc/passwd` is handled.
- `docs/CONFIGURATION.md` with the full environment variable reference.
- `docs/TROUBLESHOOTING.md` covering ACL, port conflict and LXC idmap issues.
- `.env.example`: every setting is now configurable without editing
  `docker-compose.yml`.
- GitHub issue and pull request templates, and a CI workflow that builds the
  image and byte-compiles the Python sources on every push.
- `.gitignore` covering runtime state, so the SQLite database and the
  persisted `/etc/shadow` copies can no longer be committed by accident.

### Changed
- Repository layout flattened: the contents of `smb-user-manager/` are now at
  the repository root, which is what `git clone` users expect.
- Default web UI port published on the host is now `8000` instead of `80`,
  configurable through `WEB_PORT`.
- Host data path, Samba share section, session TTL and timezone are read from
  the environment instead of being hardcoded in the compose file.
- Comments across the Dockerfile, the entrypoint and the install script
  translated to English.

### Removed
- The duplicated older copy of the application that lived at the repository
  root.
- `update.sh`, `cleanup.sh` and `reset-repo-from-prod.sh`: deployment scripts
  tied to the author's own server layout. Updating is now
  `git pull && docker compose up -d --build`.

[Unreleased]: https://github.com/Andrea52-jimny/HomeLab-smbUserManager/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Andrea52-jimny/HomeLab-smbUserManager/releases/tag/v1.0.0
