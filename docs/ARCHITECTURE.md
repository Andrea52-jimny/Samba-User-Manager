# Architecture

Why this project is shaped the way it is. Read this before changing the
deployment topology — most of these constraints are not negotiable.

## One container, two processes

Samba (`smbd`) and the FastAPI application run **in the same container**.

This is deliberate, and it is not a packaging shortcut. The application
manages authentication by creating **real Linux users**:

```
useradd -M -s /usr/sbin/nologin -G smbgroup anna
smbpasswd -a anna
```

`smbd` authenticates against that same system user database. If the app ran
in a separate container, it would write into *its own* `/etc/passwd` and
`/var/lib/samba/private/passdb.tdb`, and the Samba container would never see
the user. There is no network protocol between the two to bridge that gap —
short of running a full directory service, which is a different project.

The entrypoint therefore starts both processes and supervises them: if either
exits, the other is stopped and the container exits, so Docker's restart
policy brings the whole thing back up in a consistent state.

```
/entrypoint.sh
├── seed persistent state from ./state/
├── smbd --foreground --no-process-group   &
├── uvicorn app.main:app --port 8000       &
└── wait -n  → if one dies, terminate both
```

## Why `privileged: true`

The application calls `useradd`, `usermod`, `smbpasswd`, `chage` and
`setfacl`; `smbd` binds port 445 and manipulates extended attributes. A
targeted capability set is plausible — roughly `CAP_CHOWN`, `CAP_FOWNER`,
`CAP_DAC_READ_SEARCH`, `CAP_DAC_OVERRIDE`, `CAP_SYS_ADMIN` — but it has to be
validated against your kernel, your storage driver and your LXC nesting, and
a wrong guess fails at the worst time with a confusing `Operation not
permitted`. For a homelab NAS, `privileged: true` is the simple and reliable
choice.

The consequence is in [SECURITY.md](../SECURITY.md): treat an administrator
session as root on the Samba host.

## Persisting `/etc/passwd` without breaking `useradd`

This is the subtlest part of the design, and the one most likely to be
"simplified" into a crash loop by someone refactoring the compose file.

Linux users created inside a container live in `/etc/passwd`, `/etc/shadow`,
`/etc/group` and `/etc/gshadow`. Those are inside the container's writable
layer, so they vanish when the container is recreated — every
`docker compose up --build` would wipe every Samba user.

The obvious fix is to bind-mount the four files. **It does not work.**

A bind-mounted file is a *mountpoint*. The shadow-utils family
(`useradd`, `groupadd`, `passwd`, `usermod`) does not edit those files in
place: it writes a temporary file beside the original and then calls
`rename()` over it. `rename()` cannot replace a mountpoint. The command fails
with:

```
failure while writing changes to /etc/group
```

and because the entrypoint stops on that error, the container enters a
crash loop.

So the project mounts **a directory** instead:

```
./state/users   ──▶   /persist/users     (passwd, shadow, group, gshadow)
```

and copies the files across the boundary at the two moments where it matters:

1. **At every container start**, the entrypoint copies
   `/persist/users/*` → `/etc/*`. At that point `/etc/passwd` and friends are
   ordinary files inside the container, not mountpoints, so `useradd`,
   `groupadd`, `smbpasswd` and `chage` all work normally. On the very first
   start, `/persist/users` is empty and gets seeded from `/opt/defaults/`,
   the pristine copy baked into the image.
2. **After every operation that changes users or groups** — creation,
   suspension, password reset, expiry change, deletion — the application
   copies `/etc/*` → `/persist/users/*` (see `app/samba_manager.py`). The
   change now survives the next container recreation.

If you ever see users disappearing after a rebuild, this copy-back is the
first thing to check.

## State layout

| Volume | Contents | Loss means |
|---|---|---|
| `HOST_DATA_PATH` (bind) | The actual files served over SMB | Your data |
| `./state/app-data` | SQLite: admins, sessions, expiry, audit log | Admin accounts and history |
| `./state/samba-etc` | `smb.conf` and Samba configuration | Share definition |
| `./state/samba-private` | `passdb.tdb`, `secrets.tdb` | Samba passwords |
| `./state/samba-log` | Samba logs | Nothing critical |
| `./state/users` | Persistent `passwd`/`shadow`/`group`/`gshadow` | All Samba users |

`./state/` as a whole is what you back up. It contains password hashes —
protect it accordingly.

## The filesystem is the source of truth

There is no table of folders in the database. The tree shown in the UI is
produced by `os.scandir` one level at a time (lazy loading), and the state of
each checkbox comes from parsing `getfacl` output at request time.

That has two consequences worth knowing:

- A folder created over SMB, over SSH, or by any other means shows up in the
  UI immediately — nothing to re-scan or re-index.
- An ACL changed outside the app is reflected on the next page load. The app
  will not "correct" it back to a stored value, because no such value exists.

The database records *explicit* permission grants alongside the audit log, so
the UI can distinguish "inherited from the parent" from "set deliberately on
this folder", and so `revoke-all` and `reset-inherit` know what to undo. But
the authority is always the filesystem.

## Why POSIX ACLs need help on ZFS

`setfacl` writes POSIX ACLs into extended attributes. ZFS does not enable
that by default:

```bash
zfs set acltype=posixacl pool/dataset
zfs set xattr=sa pool/dataset          # store xattrs in the inode: much faster
```

Set this on the **host**, on the dataset that backs the bind mount — not
inside the container, which usually has no `zfs` command and no authority
over the pool. Without it, every `setfacl` call fails and no permission you
grant has any effect. `aclinherit=passthrough` keeps inherited entries intact
rather than letting ZFS rewrite them.

On ext4 and XFS, POSIX ACLs are enabled by default on every modern
distribution; there is nothing to do.

## Request flow

```
  POST /api/permissions/anna  {path: "Fatture", read: true, write: true}
        │
        ├─ require_admin_api()     session cookie → SQLite lookup
        ├─ validate username       ^[a-z][a-z0-9_-]{1,31}$
        ├─ normalise path          realpath, assert it stays under SMB_ROOT_PATH
        ├─ subprocess.run(["setfacl", "-R", "-m", "u:anna:rwx", path])
        ├─ subprocess.run(["setfacl", "-R", "-d", "-m", "u:anna:rwx", path])
        ├─ record the grant + audit entry in SQLite
        └─ respond; the UI re-reads getfacl for that node
```

Every argument reaching `subprocess` is a list element, never a shell string.
A username containing `; rm -rf /` would simply fail the regex check well
before it got anywhere near a command — but even if the regex were removed,
it would be passed to `setfacl` as one literal argument, not interpreted.
