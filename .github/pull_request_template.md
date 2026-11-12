## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

Closes #

## Why

<!-- The problem this solves. -->

## How it was tested

<!-- This project touches real system users and ACLs; say what you ran it against. -->

- [ ] Deployment tested: <!-- Docker Compose / bare metal LXC -->
- [ ] Host and filesystem: <!-- e.g. Debian 12 LXC on Proxmox, ZFS posixacl -->
- [ ] Created, suspended, resumed and deleted a user
- [ ] Permissions survive a container restart

## Checklist

- [ ] No `shell=True`, and every system command uses an argument list
- [ ] Every SQL query uses `?` placeholders
- [ ] Paths coming from the client are validated against the share root
- [ ] Documentation updated (`README.md`, `README.it.md`, `docs/`) if behaviour changed
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
