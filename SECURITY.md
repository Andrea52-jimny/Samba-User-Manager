# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Report it privately through GitHub's
[security advisories](https://github.com/Andrea52-jimny/HomeLab-smbUserManager/security/advisories/new)
page for this repository. Include the version or commit, the deployment mode
and the steps to reproduce. You can expect an acknowledgement within a few
days; this is a hobby project maintained in spare time, so please allow
reasonable time for a fix before public disclosure.

## Threat model

Understand what this project is before you deploy it.

The application manages **real Linux users** and **real POSIX ACLs**. It runs
as `root` and executes `useradd`, `smbpasswd`, `usermod`, `chage` and
`setfacl`. In the Docker deployment the container runs `privileged: true`.
Anyone who gets an authenticated session, or who reaches the container's
root filesystem, effectively has root on the machine running Samba.

It is designed for a **trusted LAN** in a homelab. It is not hardened for
exposure to the public internet.

## What the project does to protect you

- Administrator passwords are stored as bcrypt hashes, never in plaintext.
- Sessions use 256-bit random opaque tokens in `HttpOnly`, `SameSite=Lax`
  cookies, with a configurable TTL (12 hours by default), revocable
  server-side.
- Every system command is executed with an argument list through
  `subprocess`; `shell=True` is never used, so values coming from the web UI
  cannot be interpreted as shell syntax.
- All SQL uses parameterised statements.
- Usernames are validated against `[a-z][a-z0-9_-]{1,31}`.
- Every path received from the frontend is normalised and checked against the
  configured share root before reaching an ACL command, to block traversal.
- `smb.conf` is validated with `testparm -s` after every automated change and
  rolled back from a timestamped backup if validation fails.

## What you must do

1. **Change the bootstrap password** (`admin` / `ChangeMe123!`) at the first
   login. Nothing else in this list matters if you skip this one.
2. **Do not expose the web UI to the internet.** Keep it on the LAN, or reach
   it over a VPN such as WireGuard or Tailscale.
3. If you do put it behind a reverse proxy with TLS, set
   `SESSION_COOKIE_SECURE=true`.
4. **Back up `state/`** — and treat those backups as secrets, because they
   contain `/etc/shadow` copies and the Samba password database.
5. Keep the host, the base image and the Python dependencies updated:
   `docker compose build --pull --no-cache`.

## Supported versions

Only the latest release on `main` receives fixes.
