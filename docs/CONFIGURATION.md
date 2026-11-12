# Configuration reference

Every setting is an environment variable. With Docker Compose, put them in a
`.env` file next to `docker-compose.yml` (start from `.env.example`). With
the bare-metal install, add `Environment=` lines to
`/etc/systemd/system/smb-user-manager.service`.

Defaults come from `app/config.py` and the `Dockerfile`.

## Storage and Samba

| Variable | Default | Description |
|---|---|---|
| `HOST_DATA_PATH` | `/mnt/dati` | **Compose only.** Host directory bind-mounted into the container. Must be on a filesystem with POSIX ACL support. |
| `SMB_ROOT_PATH` | `/mnt/dati` | Path of the share root *inside* the container. Must equal the `path =` option of the managed share in `smb.conf`. The folder tree in the UI is rooted here, and no ACL operation is ever allowed outside it. |
| `SMB_CONF_PATH` | `/etc/samba/smb.conf` | Samba configuration file the app reads and patches. |
| `SMB_SHARE_SECTION` | `Dati` | Name of the `smb.conf` section this app manages. If you rename the share, change this too, or the `force user` detection and the automatic fix will not find it. |
| `SAMBA_GROUP` | `smbgroup` | System group every managed user is added to. Referenced by `valid users = @smbgroup` in the share. |
| `NOLOGIN_SHELL` | `/usr/sbin/nologin` | Login shell assigned to managed users. They are file-sharing accounts and must not be able to log in interactively. |

## Application state

| Variable | Default | Description |
|---|---|---|
| `SMB_DB_PATH` | `<project>/data/smb_manager.db` (`/app/data/smb_manager.db` in the image) | SQLite database holding administrators, sessions, expiry dates, explicit grants and the audit log. |
| `PERSIST_USERS_DIR` | empty (`/persist/users` in Compose) | Directory where copies of `passwd`, `shadow`, `group` and `gshadow` are kept so Linux users survive container recreation. **Leave empty on a bare-metal install** — there is nothing to persist across, and setting it would copy system files pointlessly. See [ARCHITECTURE.md](ARCHITECTURE.md#persisting-etcpasswd-without-breaking-useradd). |

## Administration

| Variable | Default | Description |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Bootstrap administrator username. |
| `ADMIN_PASSWORD` | `ChangeMe123!` | Bootstrap administrator password. |

Both are read **only** by `init_db.py`, which runs on the very first start
when no database exists. Changing them later has no effect on an existing
installation — use the "Change password" button in the dashboard instead. If
you need to reset a forgotten password, delete `state/app-data/` and restart;
you lose administrators, sessions and the audit log, but not Samba users or
permissions.

## Sessions

| Variable | Default | Description |
|---|---|---|
| `SESSION_TTL_HOURS` | `12` | Lifetime of an administrator session. Tokens are opaque 256-bit random values stored server-side and revocable at logout. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` **only** when the UI is served over HTTPS. With `true` on a plain-HTTP deployment, the browser discards the cookie and login appears to silently fail. |

The cookie is always `HttpOnly` and `SameSite=Lax`; neither is configurable.

## Behaviour

| Variable | Default | Description |
|---|---|---|
| `EXPIRY_CHECK_INTERVAL_SECONDS` | `60` | How often the background worker scans for accounts past their expiry time and suspends them. Lower values shorten the worst-case delay between the configured expiry and the actual suspension; the scan is cheap. |

## Container

| Variable | Default | Description |
|---|---|---|
| `TZ` | `Europe/Rome` | **Set this to your own timezone.** Expiry times are entered in the browser as local wall-clock values with no offset, and compared against the container clock. A container on UTC and an administrator on CEST produce a systematic two-hour error. |
| `WEB_PORT` | `8000` | **Compose only.** Host port published for the web UI. |
| `SMB_PORT` | `445` | **Compose only.** Host port published for SMB. |

`TZ` is also a build argument in the `Dockerfile`, which sets
`/etc/localtime`. To change it properly:

```bash
docker compose build --build-arg TZ=America/New_York
```

and set `TZ` to the same value in `.env`.

## Ports

The web UI listens on `8000` inside the container; `WEB_PORT` only changes
what the host publishes. To serve the UI on port 80, set `WEB_PORT=80` — do
not edit the uvicorn command.

Port `139` (NetBIOS) is deliberately **not** published. It almost always
collides with an `nmbd` already running on the host or LXC container, and the
stack then fails to start with `address already in use`. Modern clients use
445 exclusively. If you genuinely need 139 for Windows XP or Server 2003 era
clients, uncomment the mapping in `docker-compose.yml` after freeing the port
— see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#address-already-in-use-on-port-139-or-445).

## Reverse proxy

If you put the UI behind a TLS-terminating proxy:

1. set `SESSION_COOKIE_SECURE=true`;
2. forward `Host`, `X-Forwarded-Proto` and `X-Forwarded-For`;
3. do not proxy port 445 — SMB is not HTTP and must reach the container
   directly.

Exposing the UI to the public internet is not recommended at all; see
[SECURITY.md](../SECURITY.md).
