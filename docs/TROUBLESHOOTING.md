# Troubleshooting

Start here before opening an issue. Roughly in order of how often each one
bites people.

---

## Permissions have no effect: everyone sees everything

**By far the most common problem.** Check `smb.conf` for this:

```ini
[Dati]
    force user = smbuser
```

`force user` makes every connection act on the filesystem as that one user,
no matter who authenticated. The filesystem never sees the real user, so
per-user ACLs have nothing to match and are silently ignored.

**Fix:** open the dashboard. The "Samba configuration" card detects this and
offers **Fix configuration now**, which backs up `smb.conf`, removes the
option, sets `valid users = @smbgroup`, validates with `testparm -s` and
reloads Samba. Clients must reconnect — Windows caches SMB sessions, so run
`net use * /delete` or sign out and back in.

Also check for `force group`, `guest ok = yes` and `map to guest = Bad User`
reaching your share: each can bypass per-user identity in its own way.

---

## `setfacl: Operation not supported`

The filesystem under the share does not have POSIX ACL support enabled.

**ZFS** — set this on the **host**, not in the container:

```bash
zfs get acltype,xattr pool/dataset
zfs set acltype=posixacl pool/dataset
zfs set xattr=sa pool/dataset
zfs set aclinherit=passthrough pool/dataset
```

Existing files keep working; the setting applies from that point on. If the
dataset was mounted before the change, remount it.

**ext4 / XFS** — ACLs are on by default on modern distributions. If someone
has explicitly mounted with `noacl`, remove it from `/etc/fstab` and remount.

Verify from inside the container:

```bash
docker compose exec smb-user-manager setfacl -m u:nobody:r /mnt/dati && echo OK
```

---

## Unprivileged LXC: `Operation not permitted`

In an unprivileged LXC container, UIDs are remapped: container `root` (UID 0)
is, say, UID 100000 on the host. Two things break.

1. `useradd`, `chown` and `setfacl` may be refused because the container's
   root is not the owner of the bind-mounted files on the host.
2. ACLs written inside the container refer to container UIDs, which do not
   match the file ownership the host sees. Permissions then appear to be set
   but do not apply.

**Check** that the numeric UIDs agree on both sides:

```bash
ls -ln /mnt/dati          # on the host
ls -ln /mnt/dati          # inside the container — must show the same numbers
```

**Options**, in order of how much pain they save you:

- Use a **privileged** LXC container for the Samba host. Simplest, and the
  usual choice for a homelab NAS.
- Keep it unprivileged and configure a matching `lxc.idmap` in the Proxmox
  container config, so a range of container UIDs maps onto the host UIDs that
  own the dataset.

Do not proceed to production until `ls -ln` agrees on both sides.

---

## `address already in use` on port 139 or 445

Something else on the host or LXC container is already serving SMB — almost
always a native `smbd`/`nmbd` installed before you moved to Docker.

```bash
ss -tulpn | grep -E ':139|:445|:8000'
```

If it is a native Samba, and Docker is now your single source of truth:

```bash
systemctl disable --now smbd nmbd
```

Port `139` is not published by default precisely because of this. Only
uncomment it in `docker-compose.yml` after the port is free, and only if you
need Windows XP / Server 2003 era clients.

---

## Users disappear after `docker compose up --build`

The copy-back of `/etc/passwd` and friends into `./state/users` is not
happening, or the volume is not mounted.

```bash
ls -la state/users/      # should contain passwd, shadow, group, gshadow
docker compose exec smb-user-manager ls -la /persist/users
```

Both must show the four files, and `state/users/passwd` should contain the
users you created. If `/persist/users` is empty, the volume line is missing
from `docker-compose.yml`. If it exists but is stale, check
`PERSIST_USERS_DIR` is set in the environment.

Never "simplify" this by bind-mounting the four files directly — that breaks
`useradd` and crash-loops the container. The reason is in
[ARCHITECTURE.md](ARCHITECTURE.md#persisting-etcpasswd-without-breaking-useradd).

---

## Container crash loop: `failure while writing changes to /etc/group`

You are bind-mounting `/etc/group` (or `passwd`, `shadow`, `gshadow`) as an
individual file. `groupadd` writes a temporary file and calls `rename()` over
the original, and `rename()` cannot replace a mountpoint.

Replace those four file mounts with the single directory mount:

```yaml
- ./state/users:/persist/users
```

and let the entrypoint copy them into `/etc` at start.

---

## Login does nothing, or immediately bounces back to the login page

`SESSION_COOKIE_SECURE=true` while serving over plain HTTP. The browser
refuses to store a `Secure` cookie on an insecure origin, so the session is
lost the moment it is created.

Set it to `false`, or put the app behind an HTTPS reverse proxy.

---

## Account expiry fires at the wrong time

The container's timezone does not match yours. Expiry times are entered in
the browser as local wall-clock values with no offset, and compared against
the container clock — a container on UTC and an administrator on CEST are two
hours apart.

```bash
docker compose exec smb-user-manager date
```

Set `TZ` in `.env`, and rebuild with the matching build argument so
`/etc/localtime` agrees:

```bash
docker compose build --build-arg TZ=Europe/Rome
docker compose up -d
```

---

## A user can read but cannot delete files

Expected, and not a bug. On POSIX filesystems the right to delete a file
comes from write permission on the **containing directory**, not from a bit
on the file. Grant Write together with Delete on the parent folder.

See the note in the [README](../README.md#how-permissions-work).

---

## New files created by one user are not readable by another

Check `create mask` and `directory mask` in the share. The defaults shipped
here are:

```ini
create mask = 0660
directory mask = 0770
```

These strip the "other" bits, which is what you want when access is granted
through ACLs rather than through the classic owner/group/other triad. If you
tightened them to `0600`/`0700`, group and ACL entries get masked away.

Also check the ACL **mask** entry — `getfacl` shows it as `mask::`. An
overly restrictive mask clamps every named user entry:

```bash
getfacl /mnt/dati/Fatture
```

---

## Changes do not show up in the browser

The folder tree is read live from disk, so a hard refresh is usually enough
(`Ctrl+Shift+R`). If the UI still disagrees with `getfacl`, you are probably
looking at a different path than you think — confirm `SMB_ROOT_PATH` matches
the `path =` option of the share.

---

## Still stuck

Collect this before opening an issue:

```bash
docker compose logs --tail=100
docker compose exec smb-user-manager testparm -s
getfacl -R /mnt/dati | head -50
zfs get acltype,xattr pool/dataset     # if on ZFS
ls -ln /mnt/dati
```

Redact anything you would rather not publish, and **never paste the contents
of `state/`** — it holds password hashes.
