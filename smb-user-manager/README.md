# Samba Access Manager

Web app per la gestione di utenti Samba e permessi granulari POSIX ACL,
pensata per girare dentro un container LXC con storage bind-mount da un
pool ZFS dell'host.

## Stack

- Backend: Python + FastAPI, comandi di sistema via `subprocess` (liste di
  argomenti, mai `shell=True`).
- Database: SQLite (sessioni admin, stato utenti, scadenze, permessi
  espliciti, log attivita').
- Frontend: HTML5 + Tailwind CSS (CDN) + JavaScript vanilla.
- Sicurezza: Bcrypt per le password admin, query parametrizzate ovunque
  (prepared statements), cookie di sessione HttpOnly.

## Struttura del progetto

```
smb-user-manager/
  backend/
    main.py              entry point FastAPI + tutte le route
    config.py             configurazione da variabili d'ambiente
    database.py           connessione SQLite + schema
    init_db.py             script di bootstrap (da eseguire una volta)
    auth.py                login admin, hashing, sessioni
    samba_manager.py      useradd/smbpasswd/chage/deluser
    acl_manager.py         scansione dinamica cartelle + setfacl/getfacl
    smbconf_manager.py     riscrittura sicura di smb.conf
    requirements.txt
  frontend/
    templates/            login.html, dashboard.html, permissions.html
    static/js/             common.js, dashboard.js, permissions.js
    static/css/custom.css
  install.sh                script di installazione per il container LXC
  smb-user-manager.service  unit file systemd
```

## Installazione nel container LXC

```bash
cd /opt
git clone <questo-progetto> smb-user-manager   # oppure copia la cartella
cd smb-user-manager
chmod +x install.sh
./install.sh
```

Lo script:
1. installa `samba`, `acl`, Python;
2. crea il gruppo di sistema `smbgroup`;
3. verifica/imposta `acltype=posixacl` sul dataset ZFS corrispondente a
   `/mnt/dati` (necessario altrimenti **setfacl non funziona affatto** su
   ZFS);
4. imposta i permessi di base sulla cartella radice;
5. crea il virtualenv Python e installa le dipendenze;
6. inizializza il database SQLite e un amministratore di bootstrap
   (`admin` / `ChangeMe123!` di default, sovrascrivibile con le variabili
   d'ambiente `ADMIN_USERNAME` / `ADMIN_PASSWORD`);
7. installa e avvia il servizio systemd `smb-user-manager`.

Accesso: `http://<ip-container>:8000` — **cambiare subito la password admin**
dal pulsante "Cambia password" in dashboard.

## Correzione della configurazione Samba (force user)

Il file `smb.conf` fornito ha, nella sezione `[Dati]`:

```
force user = smbuser
```

Con questa riga attiva, il filesystem vede sempre `smbuser` indipendentemente
da chi si connette: le ACL per-utente sarebbero inutili. Dalla dashboard,
la card "Configurazione Samba" mostra lo stato e offre il pulsante
**"Correggi configurazione ora"**, che:

- rimuove `force user = smbuser`;
- imposta `valid users = @smbgroup`;
- fa un backup timestampato di `smb.conf` prima di scrivere;
- valida il risultato con `testparm -s` (ripristina il backup se non valido);
- ricarica Samba (`smbcontrol smbd reload-config`).

Questa operazione **non e' automatica all'avvio**: e' un'azione esplicita
dell'amministratore, visibile e reversibile (backup sempre disponibile in
`/etc/samba/smb.conf.bak-<timestamp>`).

## Come funzionano i permessi granulari

Ogni cartella/sottocartella e' letta **in tempo reale** dal disco
(`os.scandir`, caricamento lazy per-livello): non esiste alcun record
statico delle cartelle nel database. Se sul disco compare una nuova
cartella, la prossima apertura dell'albero la mostra automaticamente.

Le 3 checkbox (Lettura, Modifica, Eliminazione) vengono tradotte in bit
POSIX ACL con `setfacl`:

| Checkbox     | Bit ACL sulla directory |
|--------------|--------------------------|
| Lettura      | `r`                      |
| Modifica     | `w`                      |
| Eliminazione | `w`                      |
| (traversal)  | `x` se almeno un permesso e' attivo |

**Nota tecnica**: in POSIX, la cancellazione di un file dipende dal permesso
di scrittura sulla cartella che lo contiene, non da un bit dedicato sul
singolo file (a differenza delle ACL NTFS di Windows). Per questo Modifica
ed Eliminazione condividono lo stesso bit `w` a livello di filesystem, pur
restando due controlli distinti in interfaccia e nel database (utile per
audit e per future estensioni).

Ereditarieta': ogni assegnazione imposta sia le ACL effettive ricorsive
sull'albero esistente (`setfacl -R -m ...`) sia le ACL di default sulla
cartella (`setfacl -d -m ...`), cosi' che i contenuti creati in futuro le
ereditino automaticamente. Un permesso impostato esplicitamente su una
sottocartella specifica sovrascrive quanto ereditato dal genitore, perche'
viene scritto puntualmente su quel percorso (bottone "Applica (solo qui)"
per non toccare l'albero sottostante, "Applica (ricorsivo)" per applicarlo
in cascata).

## Sospensione utente

Il pulsante ⏸️ chiama `smbpasswd -d <username>`, che disabilita
immediatamente l'autenticazione Samba per quell'utente: non potra' piu'
aprire alcuna sessione ne' vedere alcuna cartella condivisa. Lo stato viene
anche salvato nel database (`suspended = 1`) e, come difesa aggiuntiva,
l'account Linux viene bloccato con `usermod -L`. Il pulsante ▶️ inverte
l'operazione (`smbpasswd -e` + `usermod -U`).

Un thread di background controlla ogni 5 minuti (configurabile con
`EXPIRY_CHECK_INTERVAL_SECONDS`) gli utenti con scadenza superata e li
sospende automaticamente.

## Sincronizzazione password Unix/Samba

La configurazione fornita ha gia' `unix password sync = yes` e
`passwd program = /usr/bin/passwd %u`: quando l'app imposta la password con
`smbpasswd -s`, il sistema sincronizza automaticamente anche la password
Unix. Per questo non viene mai chiamato `chpasswd` separatamente.

## Note per container LXC non privilegiati

- Se il container e' *unprivileged*, verificare che le idmap consentano le
  operazioni `setfacl`/`chown`/`useradd` come root nel container (altrimenti
  si ottengono errori tipo `Operation not permitted`).
- Se lo storage e' un bind mount da un host ZFS, il pool sull'HOST deve
  avere `acltype=posixacl` (l'app verifica questo automaticamente quando il
  comando `zfs` e' disponibile nel container; se il container non lo ha
  installato, va verificato manualmente sull'host).

## Sicurezza

- Password admin: Bcrypt, mai in chiaro.
- Tutte le query SQL: prepared statement con placeholder `?`.
- Sessioni: token casuali da 256 bit, cookie HttpOnly/SameSite=Lax, scadenza
  configurabile (default 12h).
- Validazione input: username vincolato a `[a-z][a-z0-9_-]{1,31}`, password
  minimo 8 caratteri, path delle cartelle sempre normalizzato e verificato
  contro path traversal prima di ogni comando ACL.
- Dietro reverse proxy TLS, impostare `SESSION_COOKIE_SECURE=true`.
