# Samba Manager — Web App gestione utenti e permessi granulari

Web app per amministrare utenti Samba e permessi POSIX ACL granulari sulla
condivisione `/mnt/dati`, pensata per girare dentro un container LXC con
bind mount da un pool ZFS dell'host.

## Stack

- **Backend:** Python + FastAPI, comandi di sistema via `subprocess` (liste
  di argomenti, mai `shell=True` → nessuna superficie di command injection)
- **Database:** SQLite (`data/samba_manager.db`) — traccia sessioni admin,
  sospensioni, scadenze account. La fonte di verità per i permessi reali
  resta sempre il file system (POSIX ACL), letto live via `getfacl`.
- **Frontend:** HTML + Tailwind (via CDN) + JavaScript vanilla, albero
  cartelle caricato in modo asincrono e ricorsivo (lazy loading)
- **Sicurezza:** Bcrypt per le password admin, Prepared Statements SQLite
  ovunque, sessioni via token opachi revocabili, validazione rigorosa degli
  username, anti path-traversal su ogni percorso ricevuto dal frontend

## Struttura dei file

```
samba-manager/
├── install.sh                      # setup automatico dentro il container LXC
├── init_db.py                      # crea lo schema DB + primo admin (interattivo)
├── requirements.txt
├── samba-manager.service           # unit systemd
├── smb.conf.dati.corretto.example  # riferimento della sezione [Dati] corretta
├── app/
│   ├── config.py            # percorsi, nomi gruppo, costanti
│   ├── database.py          # schema SQLite + connessione
│   ├── security.py          # bcrypt + gestione sessioni
│   ├── shell.py             # wrapper sicuro per subprocess
│   ├── system_users.py      # useradd/userdel/smbpasswd
│   ├── acl_manager.py       # scansione albero + setfacl/getfacl
│   ├── smb_conf_manager.py  # fix automatico di "force user" in smb.conf
│   ├── scheduler.py         # auto-sospensione account scaduti
│   ├── models.py            # schemi Pydantic
│   └── main.py              # route FastAPI
├── templates/                # login.html, dashboard.html, permissions.html
└── static/{css,js}/          # stile e logica client-side
```

## Installazione

```bash
# dentro il container LXC, come root
cd /root && git clone/copy della cartella samba-manager qui
cd samba-manager
bash install.sh
```

Poi:

```bash
cd /opt/samba-manager
source venv/bin/activate
python init_db.py          # crea il primo amministratore (username+password)
systemctl start samba-manager
```

Apri `http://<ip-container>:8000`.

## Come funziona la correzione di `force user`

Il brief segnala correttamente che `force user = smbuser` nella sezione
`[Dati]` di `smb.conf` rende inutili le ACL per-utente, perché il file
system vede sempre `smbuser` indipendentemente da chi si collega. La
dashboard rileva questa condizione (`GET /api/smb-status`) e mostra un
banner con un pulsante "Correggi automaticamente" che:

1. crea un backup con timestamp di `smb.conf`,
2. rimuove `force user` dalla sezione `[Dati]`,
3. imposta `valid users = @smbgroup`,
4. valida la nuova configurazione con `testparm -s` (rollback automatico se non valida),
5. ricarica Samba con `smbcontrol all reload-config`.

## Permessi: come funziona l'ereditarietà

Assegnare Lettura/Modifica/Eliminazione su una cartella esegue:

```bash
setfacl -R -m u:USERNAME:PERM   <cartella>   # ACL effettiva su tutto il sotto-albero esistente
setfacl -R -d -m u:USERNAME:PERM <cartella>  # ACL di default → eredita anche sui contenuti FUTURI
```

Applicare un permesso diverso su una sottocartella specifica sovrascrive
semplicemente l'ACL su quel ramo, realizzando l'override esplicito richiesto
dal brief. Le checkbox mostrate nell'interfaccia riflettono sempre lo stato
**reale e attuale** letto da `getfacl`, non un valore salvato staticamente.

> **Nota sui bit POSIX:** le tre checkbox sono mappate 1:1 su `r` (Lettura),
> `w` (Modifica), `x` (Eliminazione) come richiesto. Su Linux, però,
> l'eliminazione di un file dipende in realtà dal permesso di **scrittura
> sulla cartella che lo contiene**, non da un bit sul file stesso: per un
> comportamento coerente, abilita "Elimina" insieme a "Modifica".

## Avviso operativo importante: LXC e mapping UID

Se il container LXC è **non privilegiato** (default su Proxmox), gli UID
degli utenti Linux creati dentro il container vengono rimappati con un
offset quando visti dall'host. Se il bind mount ZFS non ha un mapping UID
coerente configurato lato host (`lxc.idmap` in Proxmox, o equivalente),
le ACL POSIX applicate dentro il container potrebbero non corrispondere
alla proprietà reale dei file sull'host. Verifica con `ls -ln` sia dentro
il container che sull'host che gli UID numerici combacino prima di andare
in produzione; in caso contrario, valuta un container privilegiato o
configura un idmap dedicato.

## Sicurezza in rete locale (nessun TLS)

Il cookie di sessione è impostato con `Secure=false` di default
(`SM_COOKIE_SECURE=false` nella unit systemd), pensato per un accesso via
`http://ip-lxc:8000` sulla LAN. Se esponi l'app oltre la LAN, mettila
dietro un reverse proxy con TLS e imposta `SM_COOKIE_SECURE=true`.

## Riavvio / manutenzione

```bash
systemctl status samba-manager
systemctl restart samba-manager
journalctl -u samba-manager -f
```

I backup di `smb.conf` restano in `/etc/samba/smb.conf.bak-<timestamp>`.
