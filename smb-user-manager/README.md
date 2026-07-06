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
  app/                       pacchetto Python (import relativi tra i moduli)
    __init__.py
    main.py                  entry point FastAPI + tutte le route
    config.py                configurazione da variabili d'ambiente
    database.py              connessione SQLite + schema
    auth.py                  login admin, hashing, sessioni
    samba_manager.py         useradd/smbpasswd/chage/deluser
    acl_manager.py           scansione dinamica cartelle + setfacl/getfacl
    smbconf_manager.py       riscrittura sicura di smb.conf
  static/                    css/js
  templates/                 login.html, dashboard.html, permissions.html
  init_db.py                 script di bootstrap (da eseguire una volta)
  requirements.txt
  install.sh                 installazione diretta su LXC/VM (senza Docker)
  smb-user-manager.service   unit file systemd (percorso non-Docker)
  update.sh / cleanup.sh / reset-repo-from-prod.sh   deploy non-Docker
  Dockerfile / docker-compose.yml / docker/          percorso containerizzato
```

L'app si avvia sempre come `uvicorn app.main:app` (non piu' `main:app`),
dalla cartella radice del progetto.

## Due modalita' di deployment

Sono supportate entrambe le modalita' viste finora nel progetto:

1. **LXC/VM diretto** (`install.sh` + systemd): vedi sezione successiva.
2. **Docker / docker compose** (consigliato per aggiornamenti piu' semplici):
   vedi la sezione "Deployment con Docker" piu' sotto.

## Installazione diretta (LXC/VM, senza Docker)

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

Per aggiornare in seguito: `./update.sh` (vedi commenti nello script). Per
pulire i residui di vecchie versioni: `./cleanup.sh` (dry-run di default,
`--force` per eseguire davvero).

## Deployment con Docker

Un'unica immagine contiene sia `smbd` sia la Web App: devono girare nello
stesso container perche' l'app crea utenti Linux reali (`useradd`,
`smbpasswd`) che Samba deve vedere nello stesso namespace di sistema.

```bash
cd smb-user-manager
./docker/prepare-state.sh   # crea ./state/ con i file vuoti necessari (una tantum)
docker compose up -d --build
```

Poi, per ogni aggiornamento futuro (dopo un `git pull` sul codice):

```bash
docker compose up -d --build
```

Nessuno script di sincronizzazione manuale: l'immagine viene ricostruita con
il nuovo codice, i container vengono ricreati, ma i dati persistono grazie ai
volumi.

### Perche' serve `./docker/prepare-state.sh`

Se un percorso bind-mount non esiste ancora sull'host, Docker lo crea come
**directory**, non come file. `/etc/passwd`, `/etc/shadow`, `/etc/group` e
`/etc/gshadow` devono invece essere singoli file dentro il container (sono
montati individualmente per persistere gli utenti Linux creati dall'app tra
una ricreazione del container e l'altra). Lo script li pre-crea vuoti sul
host; l'entrypoint del container li popola con i default di sistema al primo
avvio se li trova vuoti.

### Volumi persistenti (`docker-compose.yml`)

| Volume host           | Contenuto                                             |
|------------------------|--------------------------------------------------------|
| `/mnt/dati` (bind reale)| I dati NAS veri, stesso path usato in `smb.conf`       |
| `./state/app-data`     | Database SQLite dell'app                                |
| `./state/samba-etc`    | `smb.conf` e configurazione Samba                       |
| `./state/samba-private`| Database utenti Samba (`passdb.tdb`, `secrets.tdb`, ...)|
| `./state/samba-log`    | Log di Samba                                            |
| `./state/passwd` ecc.  | Utenti/gruppi Linux di sistema (persistenti)            |

### Perche' `privileged: true`

L'app esegue `useradd`, `smbpasswd`, `setfacl`, `chage` a livello di sistema
e `smbd` deve gestire ACL e aprire socket privilegiati. In alternativa si
puo' provare un set mirato di `cap_add` (es. `CAP_DAC_READ_SEARCH`,
`CAP_CHOWN`, `CAP_FOWNER`, `CAP_SYS_ADMIN`), ma va validato caso per caso;
`privileged: true` e' la scelta piu' semplice e affidabile per un homelab.

### Porte

`8000` (Web UI), `445` (SMB). Per usare la porta `80` per la UI, cambia
`"8000:8000"` in `"80:8000"` in `docker-compose.yml` (non serve toccare
nulla dentro il container).

Il mapping della porta `139` (NetBIOS) e' commentato di default nel
`docker-compose.yml`: se il container LXC ha ancora `nmbd`/`smbd` nativi in
esecuzione (installati prima di passare a Docker), vanno in conflitto con
quelli dentro il container Docker e il `docker compose up` fallisce con
`address already in use`. Per capire cosa occupa una porta sul container/host:

```bash
ss -tulpn | grep -E ':139|:445|:8000'
```

Se risulta `smbd`/`nmbd` nativo, e hai deciso di usare Docker come unica
fonte di verita' per Samba, disattivalo definitivamente:

```bash
systemctl disable --now smbd nmbd
```

Solo dopo aver liberato la porta ha senso riattivare `"139:139"` in
`docker-compose.yml` (serve solo per client Windows molto vecchi tipo
XP/2003; i client moderni usano esclusivamente la 445).

### Nota sul dataset ZFS (host)

Come nel percorso non-Docker, il dataset ZFS che fa da backend a `/mnt/dati`
deve avere `acltype=posixacl` sull'HOST (fuori da Docker):

```bash
zfs set acltype=posixacl pool/dataset
zfs set xattr=sa pool/dataset
```

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
