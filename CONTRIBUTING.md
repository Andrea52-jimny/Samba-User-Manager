# Contributing

Thanks for taking the time to contribute. This is a homelab project: issues
that describe a real-world setup carefully are as valuable as pull requests.

## Reporting a bug

Open an issue with the **Bug report** template and include:

- how you deployed (Docker Compose, or bare-metal install script);
- host OS and whether Samba runs in an LXC container, a VM or bare metal;
- the filesystem behind the share (ZFS, ext4, XFS, btrfs) and, for ZFS,
  the output of `zfs get acltype,xattr <pool>/<dataset>`;
- the relevant container logs (`docker compose logs --tail=100`) or
  `journalctl -u smb-user-manager -n 100 --no-pager`.

Please redact real usernames, hostnames and paths you would rather not
publish. Never paste the contents of `state/` — it holds password hashes.

## Proposing a change

1. Open an issue first for anything beyond a typo or an obvious fix, so the
   design can be agreed before you write code.
2. Fork, branch from `main`, keep the change focused on one thing.
3. Follow the conventions below.
4. Open a pull request against `main` and fill in the template.

## Development setup

```bash
git clone https://github.com/Andrea52-jimny/HomeLab-smbUserManager.git
cd HomeLab-smbUserManager
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

The app calls real system tools (`useradd`, `smbpasswd`, `setfacl`,
`testparm`). Running it outside a container will create real users on your
machine, so **develop against a throwaway VM or container**, never your
workstation. The quickest sandbox is the project's own image:

```bash
./docker/prepare-state.sh
docker compose up --build
```

Point `SMB_ROOT_PATH` and `HOST_DATA_PATH` at a scratch directory while
testing.

## Code conventions

- **Python**: standard library and FastAPI only, no new runtime dependency
  without discussion. 4-space indent, type hints on new function signatures.
- **System commands**: always `subprocess.run([...])` with an argument list.
  `shell=True` is never acceptable — it reintroduces command injection on
  values that come from the web UI.
- **SQL**: parameterised queries with `?` placeholders only, never string
  interpolation.
- **Paths from the client**: normalise and verify they stay inside
  `SMB_ROOT_PATH` before passing them to any ACL command.
- **Frontend**: vanilla JavaScript, no build step, no bundler. Tailwind comes
  from a CDN on purpose so the project stays a single `docker compose up`.
- **Comments and identifiers**: English. User-facing UI strings may stay in
  Italian until the interface is internationalised.

## Commit messages

Short imperative subject line, one logical change per commit:

```
Add audit log pagination
Fix setfacl failure on paths containing spaces
```

## Testing a change by hand

There is no automated test suite yet (contributions welcome). Before opening
a pull request, verify at least:

- a user can be created, suspended, resumed and deleted;
- permissions set on a folder survive a container restart;
- `docker compose up -d --build` on an existing `state/` directory keeps all
  users and permissions intact.
