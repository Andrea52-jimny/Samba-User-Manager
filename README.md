<div align="center">

# SMB User Manager

**A self-hosted web UI for Samba users and per-folder POSIX ACL permissions.**

Create Samba users, set granular read / write / delete permissions on any
folder of your share, suspend accounts and give them expiry dates — from a
browser, without touching `smbpasswd` or `setfacl` by hand.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/Andrea52-jimny/HomeLab-smbUserManager/actions/workflows/ci.yml/badge.svg)](https://github.com/Andrea52-jimny/HomeLab-smbUserManager/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/deploy-docker%20compose-2496ED.svg)](docker-compose.yml)

[Quick start](#quick-start-docker-compose) ·
[How permissions work](#how-permissions-work) ·
[Configuration](docs/CONFIGURATION.md) ·
[Architecture](docs/ARCHITECTURE.md) ·
[Troubleshooting](docs/TROUBLESHOOTING.md) ·
[Italiano](README.it.md)

</div>

<!--
  Maintainer note: add screenshots here once you have them.
  Suggested: dashboard with the user list, and the per-folder permission tree.
  Put the files in docs/screenshots/ and reference them like:
  ![Dashboard](docs/screenshots/dashboard.png)
-->

---

## What it is

If you run a Samba share in your homelab, you have probably hit this wall: the
easy setups give everyone the same access to everything, and the moment you
want "Anna can read the photos, Marco can write to the invoices folder but not
delete, nobody else sees either", you are hand-editing `smb.conf` and running
`setfacl` over SSH.

SMB User Manager is a small FastAPI application that does that for you. It
manages **real Linux users** and **real POSIX ACLs** on disk — there is no
parallel permission database that can drift out of sync. The folder tree you
see in the browser is read live from the filesystem with `os.scandir`, and the
checkboxes reflect what `getfacl` says right now.

It is built for a homelab on a trusted LAN. Read [Security](SECURITY.md)
before deciding where to put it.

## Features

- **Users** — create, delete, suspend and resume Samba users; reset passwords;
  clone an existing user's permission set onto a new one.
- **Expiry dates** — give an account a date and time after which it is
  suspended automatically by a background worker.
- **Per-folder permissions** — a lazy-loaded tree of your whole share, with
  read / write / delete checkboxes on every folder.
- **Explicit overrides** — apply a permission to one folder only, or
  recursively; a child folder can override what it inherits from its parent.
- **Real inheritance** — every grant sets both the recursive effective ACL on
  existing content and the default ACL on the folder, so files created later
  inherit it.
- **`force user` detector** — the dashboard warns you when `smb.conf` contains
  the one option that silently makes all of this pointless, and offers to fix
  it safely (backup, rewrite, `testparm` validation, rollback on failure).
- **Audit log** — every administrative action is recorded with actor and
  timestamp.
- **One container** — Samba and the web UI ship as a single image. No external
  database, no message broker, no reverse proxy required.

## How it works

```
Browser ──HTTP──▶ FastAPI app ──subprocess──▶ useradd / smbpasswd / usermod
                       │                      chage / setfacl / getfacl
                       │                      testparm / smbcontrol
                       ├──▶ SQLite  (admins, sessions, expiry, audit log)
                       └──▶ /mnt/dati  (the share — ACLs live here)
                                 ▲
                                 └── smbd serves the same tree to SMB clients
```

The SQLite database holds administrator accounts, sessions, expiry dates and
the audit log. **It is not the source of truth for permissions** — the
filesystem is. If you change an ACL with `setfacl` over SSH, the web UI shows
your change on the next page load.

System commands are always executed with an argument list through
`subprocess`, never `shell=True`, so a username typed into the web form cannot
turn into shell syntax.

## Recommended setup

**Run Samba and this app together in one dedicated container, and keep the
data on the host.**

That is a single Docker container (recommended), or a single LXC container if
you prefer a bare-metal install. The important part is that Samba and the app
share one system namespace: the app creates Linux users with `useradd`, and
`smbd` has to see those users in `/etc/passwd` to authenticate them. Split
them into two containers and nothing works — a user created on one side simply
does not exist on the other.

A typical Proxmox homelab ends up like this:

```
Proxmox host
└── ZFS dataset  tank/dati     (acltype=posixacl, xattr=sa)
        │  bind mount
        ▼
    LXC container (Debian 12, privileged)
    └── Docker
        └── smb-user-manager container
            ├── smbd            ──▶ serves \\host\Dati on port 445
            ├── FastAPI web UI  ──▶ port 8000
            └── ./state/        ──▶ persistent users, Samba DB, SQLite
```

Two rules that will save you an evening of debugging:

1. **The filesystem under your share must support POSIX ACLs.** On ZFS that
   means `acltype=posixacl` and `xattr=sa` set on the **host**, outside the
   container. Without it `setfacl` fails and no permission you set has any
   effect. ext4 and XFS support ACLs out of the box on any modern distro.
2. **An unprivileged LXC container remaps UIDs.** If you use one, the UID
   mapping between host and container must be consistent, or the ACLs written
   inside the container will not match file ownership on the host. A
   privileged container is the simplest choice for a homelab NAS. See
   [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#unprivileged-lxc-operation-not-permitted).

## Requirements

| | |
|---|---|
| **Host OS** | Any Linux with Docker Engine 20.10+ and the Compose v2 plugin |
| **Filesystem** | POSIX ACL support on the share (`acltype=posixacl` on ZFS) |
| **Ports** | `8000` web UI (configurable), `445` SMB |
| **Privileges** | `root`, and `privileged: true` on the container |
| **RAM** | ~150 MB |

No Docker? See [Bare-metal install](#alternative-bare-metal-install-lxc--vm).

## Quick start (Docker Compose)

```bash
git clone https://github.com/Andrea52-jimny/HomeLab-smbUserManager.git
cd HomeLab-smbUserManager

# 1. Configure. Every value has a sensible default; the ones you will
#    actually want to change are HOST_DATA_PATH, ADMIN_PASSWORD and TZ.
cp .env.example .env
${EDITOR:-nano} .env

# 2. Create the persistent state directories (once).
./docker/prepare-state.sh

# 3. Build and start.
docker compose up -d --build
```

Open `http://<host-ip>:8000` and log in with the bootstrap administrator
(`admin` / `ChangeMe123!` unless you changed it in `.env`).

> [!IMPORTANT]
> **Change the administrator password immediately** from the "Change password"
> button in the dashboard. This application runs as root and manages system
> users; the bootstrap credentials are public knowledge.

Then, in order:

1. The dashboard shows a **Samba configuration** card. If it reports
   `force user` in your share, click **Fix configuration now** — see
   [below](#the-force-user-trap).
2. Create your first user.
3. Open their permissions page and tick what they may reach.
4. Connect from a client: `\\<host-ip>\Dati` on Windows,
   `smb://<host-ip>/Dati` on macOS and Linux.

### Before you start: your existing data

The container mounts `HOST_DATA_PATH` and applies ACLs to it directly. It does
not move or rewrite your files, but **ACLs are applied recursively** when you
grant a permission on a folder. If you are pointing this at an existing share
with a permission scheme you care about, save the current state first:

```bash
getfacl -R /mnt/dati > ~/acl-backup-$(date +%F).txt   # restore with: setfacl --restore=
```

## Configuration

Everything is set through environment variables in `.env`. The ones that
matter most:

| Variable | Default | What it does |
|---|---|---|
| `HOST_DATA_PATH` | `/mnt/dati` | Host directory holding your data |
| `SMB_ROOT_PATH` | `/mnt/dati` | Path inside the container; must match `path =` in `smb.conf` |
| `SMB_SHARE_SECTION` | `Dati` | Name of the `smb.conf` section this app manages |
| `WEB_PORT` | `8000` | Host port for the web UI |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `ChangeMe123!` | Bootstrap administrator, first start only |
| `TZ` | `Europe/Rome` | Container timezone — **must match yours**, or expiry times are off by the offset |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` behind an HTTPS reverse proxy |

The full reference, including the ones you will rarely touch, is in
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

> The default share is called `Dati` ("data" in Italian) for historical
> reasons. To rename it, change the section name in
> `state/samba-etc/smb.conf` **and** set `SMB_SHARE_SECTION` to match.

## How permissions work

Three checkboxes per folder, mapped onto POSIX ACL bits:

| Checkbox | ACL bit on the directory |
|---|---|
| Read | `r` |
| Write | `w` |
| Delete | `w` |
| *(traversal)* | `x`, added automatically when any permission is granted |

Granting a permission runs both of these:

```bash
setfacl -R -m  u:USER:PERM  /path/to/folder   # existing content
setfacl -R -d -m u:USER:PERM /path/to/folder   # default ACL → future content
```

so new files and folders created later inherit the same rights. Setting a
different permission on a subfolder overwrites the ACL on that branch only,
which is how explicit overrides work. **Apply (here only)** writes the ACL on
one folder; **Apply (recursive)** cascades it down the tree.

> [!NOTE]
> **Why Write and Delete share the same bit.** On POSIX filesystems, deleting
> a file depends on having write permission on the *containing directory*, not
> on a per-file delete bit the way Windows NTFS ACLs work. The two checkboxes
> remain separate in the UI and in the database — useful for auditing and for
> future refinements — but at the filesystem level they both resolve to `w`.
> If you want a user to be able to modify files without deleting them, POSIX
> ACLs alone cannot express that; you would need the Samba VFS layer.

## The `force user` trap

A very common Samba share config contains this line:

```ini
[Dati]
    force user = smbuser
```

It makes every connection act on the filesystem as the single user `smbuser`,
regardless of who authenticated. Per-user ACLs then have **no effect
whatsoever** — the filesystem never sees the real user, so there is nothing
for the ACL to match. This is the number one reason people conclude that
"Samba permissions don't work".

The dashboard detects it and offers a one-click fix, which:

1. takes a timestamped backup of `smb.conf`;
2. removes `force user` from the managed share;
3. sets `valid users = @smbgroup`;
4. validates the result with `testparm -s`, restoring the backup if it fails;
5. reloads Samba with `smbcontrol smbd reload-config`.

It is never applied automatically at startup — it is an explicit, reversible
administrator action, and the backups stay in `/etc/samba/smb.conf.bak-*`.

## Day-two operations

**Update**

```bash
git pull
docker compose up -d --build
```

The image is rebuilt with the new code and containers are recreated. Your
users, permissions and Samba database live in `./state/` and survive.

**Logs**

```bash
docker compose logs -f
```

**Back up** — `./state/` is everything that matters. Treat the backup as a
secret: it contains `/etc/shadow` copies and the Samba password database.

```bash
docker compose stop
tar czf smb-backup-$(date +%F).tar.gz state/
docker compose start
```

**Restore** — stop the stack, replace `state/`, start it again.

## Alternative: bare-metal install (LXC / VM)

For people already running Samba natively who do not want a container runtime.

```bash
cd /opt
git clone https://github.com/Andrea52-jimny/HomeLab-smbUserManager.git smb-user-manager
cd smb-user-manager
./install.sh          # as root
```

The script installs Samba, `acl` and Python; creates the `smbgroup` system
group; checks and sets `acltype=posixacl` on the matching ZFS dataset if `zfs`
is available; sets base permissions on the share root; builds a virtualenv;
initialises the database; and installs and starts the `smb-user-manager`
systemd unit.

```bash
systemctl status smb-user-manager
journalctl -u smb-user-manager -f
```

To update: `git pull && systemctl restart smb-user-manager`.

## API

The web UI is a thin client over a JSON API. Every endpoint except `/login`
requires a session cookie.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/login`, `/api/logout` | Session handling |
| `POST` | `/api/admin/change-password` | Change the administrator password |
| `GET` `POST` | `/api/users` | List and create users |
| `POST` | `/api/users/{u}/suspend`, `/resume` | Suspend and resume |
| `POST` | `/api/users/{u}/reset-password` | Set a new password |
| `POST` | `/api/users/{u}/expiry` | Set or clear the expiry date |
| `POST` | `/api/users/{u}/clone` | Copy permissions onto a new user |
| `DELETE` | `/api/users/{u}` | Delete the user and revoke ACLs |
| `GET` | `/api/tree`, `/api/tree/descendants` | Lazy-loaded folder tree |
| `GET` `POST` | `/api/permissions/{u}` | Read and set permissions |
| `POST` | `/api/permissions/{u}/reset-inherit`, `/revoke-all` | Reset to inherited, revoke everything |
| `GET` | `/api/system/smbconf-status` | `force user` detection |
| `POST` | `/api/system/patch-smbconf` | Apply the `smb.conf` fix |
| `GET` | `/api/audit` | Recent administrative actions |

Interactive docs are available at `/docs` while the app is running.

## Project structure

```
.
├── app/                      FastAPI application package
│   ├── main.py               routes
│   ├── config.py             configuration from environment variables
│   ├── database.py           SQLite schema and connection
│   ├── auth.py               admin login, bcrypt hashing, sessions
│   ├── samba_manager.py      useradd / smbpasswd / chage / deluser
│   ├── acl_manager.py        live folder scan, setfacl / getfacl
│   └── smbconf_manager.py    safe smb.conf rewriting
├── docker/
│   ├── entrypoint.sh         seeds persistent state, runs smbd + uvicorn
│   ├── prepare-state.sh      creates ./state/ before the first start
│   └── smb.conf.default      seed configuration for a fresh install
├── docs/                     architecture, configuration, troubleshooting
├── static/  templates/       vanilla JS and Jinja2 templates
├── Dockerfile  docker-compose.yml
├── install.sh  smb-user-manager.service     bare-metal path
└── init_db.py  requirements.txt
```

## Contributing

Issues that describe a real setup carefully are as welcome as pull requests.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and the
conventions — in particular: no `shell=True`, parameterised SQL only, and
every client-supplied path validated against the share root.

## Security

This application runs as root, manages real system users and runs in a
privileged container. Anyone with a session has effective root on the Samba
host. Keep it on your LAN or behind a VPN, and read
[SECURITY.md](SECURITY.md) before deploying. Report vulnerabilities privately
through GitHub security advisories, not in a public issue.

## License

[MIT](LICENSE) © Andrea

## Disclaimer

This software modifies system users, `smb.conf` and filesystem ACLs. Test it
against a scratch dataset before pointing it at data you care about, and keep
backups. It is provided as-is, with no warranty — see the licence.
