<div align="center">

# SMB User Manager

**Interfaccia web self-hosted per utenti Samba e permessi POSIX ACL per cartella.**

Crea utenti Samba, imposta permessi granulari di lettura / scrittura /
eliminazione su qualsiasi cartella della condivisione, sospendi account e
assegna scadenze — dal browser, senza toccare a mano `smbpasswd` o `setfacl`.

[![Licenza: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/Andrea52-jimny/HomeLab-smbUserManager/actions/workflows/ci.yml/badge.svg)](https://github.com/Andrea52-jimny/HomeLab-smbUserManager/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/deploy-docker%20compose-2496ED.svg)](docker-compose.yml)

[Avvio rapido](#avvio-rapido-docker-compose) ·
[Come funzionano i permessi](#come-funzionano-i-permessi) ·
[Configurazione](docs/CONFIGURATION.md) ·
[Architettura](docs/ARCHITECTURE.md) ·
[Risoluzione problemi](docs/TROUBLESHOOTING.md) ·
[English](README.md)

</div>

> La documentazione estesa in `docs/` è in inglese, per raggiungere la
> community internazionale. Questa pagina copre tutto il necessario per
> installare e usare il progetto.

---

## Che cos'è

Se gestisci una condivisione Samba nel tuo homelab, probabilmente hai già
sbattuto contro questo muro: le configurazioni facili danno a tutti lo stesso
accesso a tutto, e nel momento in cui vuoi «Anna legge le foto, Marco scrive
nella cartella fatture ma non cancella, gli altri non vedono né l'una né
l'altra», ti ritrovi a modificare `smb.conf` a mano e a lanciare `setfacl` via
SSH.

SMB User Manager è una piccola applicazione FastAPI che lo fa al posto tuo.
Gestisce **utenti Linux reali** e **ACL POSIX reali** su disco: non esiste un
database parallelo dei permessi che possa andare fuori sincrono. L'albero
delle cartelle che vedi nel browser è letto dal vivo dal filesystem con
`os.scandir`, e le checkbox riflettono ciò che `getfacl` dice in questo
momento.

È pensato per un homelab su LAN fidata. Leggi [SECURITY.md](SECURITY.md) prima
di decidere dove metterlo.

## Funzionalità

- **Utenti** — creazione, eliminazione, sospensione e riattivazione di utenti
  Samba; reset password; clonazione dei permessi di un utente esistente su uno
  nuovo.
- **Scadenze** — assegna a un account una data e un'ora dopo la quale viene
  sospeso automaticamente da un worker in background.
- **Permessi per cartella** — albero dell'intera condivisione a caricamento
  lazy, con checkbox lettura / scrittura / eliminazione su ogni cartella.
- **Override espliciti** — applica un permesso solo a una cartella oppure in
  modo ricorsivo; una sottocartella può sovrascrivere ciò che eredita dal
  genitore.
- **Ereditarietà reale** — ogni assegnazione imposta sia l'ACL effettiva
  ricorsiva sui contenuti esistenti sia l'ACL di default sulla cartella, così
  i file creati in futuro la ereditano.
- **Rilevamento di `force user`** — la dashboard ti avvisa quando `smb.conf`
  contiene l'unica opzione che rende silenziosamente inutile tutto questo, e
  propone di correggerla in sicurezza (backup, riscrittura, validazione con
  `testparm`, rollback in caso di errore).
- **Log di audit** — ogni azione amministrativa è registrata con autore e
  timestamp.
- **Un solo container** — Samba e la web UI in un'unica immagine. Nessun
  database esterno, nessun broker, nessun reverse proxy obbligatorio.

## Come funziona

```
Browser ──HTTP──▶ App FastAPI ──subprocess──▶ useradd / smbpasswd / usermod
                       │                      chage / setfacl / getfacl
                       │                      testparm / smbcontrol
                       ├──▶ SQLite  (admin, sessioni, scadenze, audit)
                       └──▶ /mnt/dati  (la condivisione: qui vivono le ACL)
                                 ▲
                                 └── smbd serve lo stesso albero ai client SMB
```

Il database SQLite contiene account amministratore, sessioni, scadenze e log
di audit. **Non è la fonte di verità per i permessi** — lo è il filesystem. Se
cambi un'ACL con `setfacl` via SSH, la web UI mostra la tua modifica al
caricamento successivo della pagina.

I comandi di sistema sono sempre eseguiti con una lista di argomenti tramite
`subprocess`, mai con `shell=True`: un username digitato nel form web non può
trasformarsi in sintassi di shell.

## Setup consigliato

**Fai girare Samba e questa app insieme in un container dedicato, e tieni i
dati sull'host.**

Si tratta di un singolo container Docker (consigliato), oppure di un singolo
container LXC se preferisci l'installazione diretta. La parte importante è che
Samba e l'app condividano lo stesso namespace di sistema: l'app crea utenti
Linux con `useradd`, e `smbd` deve vederli in `/etc/passwd` per autenticarli.
Separandoli in due container non funziona nulla — un utente creato da una
parte semplicemente non esiste dall'altra.

Un tipico homelab Proxmox finisce così:

```
Host Proxmox
└── Dataset ZFS  tank/dati     (acltype=posixacl, xattr=sa)
        │  bind mount
        ▼
    Container LXC (Debian 12, privilegiato)
    └── Docker
        └── container smb-user-manager
            ├── smbd            ──▶ serve \\host\Dati sulla porta 445
            ├── web UI FastAPI  ──▶ porta 8000
            └── ./state/        ──▶ utenti, DB Samba e SQLite persistenti
```

Due regole che ti risparmiano una serata di debug:

1. **Il filesystem sotto la condivisione deve supportare le ACL POSIX.** Su
   ZFS significa `acltype=posixacl` e `xattr=sa` impostati **sull'host**,
   fuori dal container. Senza, `setfacl` fallisce e nessun permesso che
   imposti ha effetto. ext4 e XFS supportano le ACL di default su qualunque
   distribuzione moderna.
2. **Un container LXC non privilegiato rimappa gli UID.** Se ne usi uno, la
   mappatura fra host e container deve essere coerente, altrimenti le ACL
   scritte dentro il container non corrispondono alla proprietà reale dei file
   sull'host. Un container privilegiato è la scelta più semplice per un NAS
   homelab. Vedi
   [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#unprivileged-lxc-operation-not-permitted).

## Requisiti

| | |
|---|---|
| **Sistema host** | Qualsiasi Linux con Docker Engine 20.10+ e il plugin Compose v2 |
| **Filesystem** | Supporto ACL POSIX sulla condivisione (`acltype=posixacl` su ZFS) |
| **Porte** | `8000` web UI (configurabile), `445` SMB |
| **Privilegi** | `root`, e `privileged: true` sul container |
| **RAM** | ~150 MB |

Niente Docker? Vedi [Installazione diretta](#alternativa-installazione-diretta-lxc--vm).

## Avvio rapido (Docker Compose)

```bash
git clone https://github.com/Andrea52-jimny/HomeLab-smbUserManager.git
cd HomeLab-smbUserManager

# 1. Configura. Ogni valore ha un default sensato; quelli che vorrai
#    davvero cambiare sono HOST_DATA_PATH, ADMIN_PASSWORD e TZ.
cp .env.example .env
${EDITOR:-nano} .env

# 2. Crea le cartelle di stato persistente (una volta sola).
./docker/prepare-state.sh

# 3. Build e avvio.
docker compose up -d --build
```

Apri `http://<ip-host>:8000` e accedi con l'amministratore di bootstrap
(`admin` / `ChangeMe123!`, se non l'hai cambiato in `.env`).

> [!IMPORTANT]
> **Cambia subito la password amministratore** dal pulsante «Cambia password»
> nella dashboard. Questa applicazione gira come root e gestisce utenti di
> sistema: le credenziali di bootstrap sono di dominio pubblico.

Poi, nell'ordine:

1. La dashboard mostra una card **Configurazione Samba**. Se segnala
   `force user` nella tua condivisione, premi **Correggi configurazione ora**
   — vedi [più sotto](#la-trappola-di-force-user).
2. Crea il primo utente.
3. Apri la sua pagina permessi e spunta ciò a cui può accedere.
4. Collegati da un client: `\\<ip-host>\Dati` su Windows,
   `smb://<ip-host>/Dati` su macOS e Linux.

### Prima di iniziare: i dati che hai già

Il container monta `HOST_DATA_PATH` e vi applica le ACL direttamente. Non
sposta né riscrive i tuoi file, ma **le ACL vengono applicate in modo
ricorsivo** quando concedi un permesso su una cartella. Se lo stai puntando su
una condivisione esistente con uno schema di permessi a cui tieni, salva prima
lo stato attuale:

```bash
getfacl -R /mnt/dati > ~/acl-backup-$(date +%F).txt   # ripristino: setfacl --restore=
```

## Configurazione

Tutto si imposta con variabili d'ambiente in `.env`. Le più importanti:

| Variabile | Default | A cosa serve |
|---|---|---|
| `HOST_DATA_PATH` | `/mnt/dati` | Cartella sull'host che contiene i dati |
| `SMB_ROOT_PATH` | `/mnt/dati` | Percorso dentro il container; deve coincidere con `path =` in `smb.conf` |
| `SMB_SHARE_SECTION` | `Dati` | Nome della sezione di `smb.conf` gestita dall'app |
| `WEB_PORT` | `8000` | Porta host per la web UI |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `ChangeMe123!` | Amministratore di bootstrap, solo al primo avvio |
| `TZ` | `Europe/Rome` | Fuso orario del container — **deve essere il tuo**, altrimenti le scadenze slittano |
| `SESSION_COOKIE_SECURE` | `false` | `true` dietro reverse proxy HTTPS |

Il riferimento completo è in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

> La condivisione di default si chiama `Dati` per ragioni storiche. Per
> rinominarla, cambia il nome della sezione in `state/samba-etc/smb.conf`
> **e** imposta `SMB_SHARE_SECTION` di conseguenza.

## Come funzionano i permessi

Tre checkbox per cartella, mappate su bit ACL POSIX:

| Checkbox | Bit ACL sulla directory |
|---|---|
| Lettura | `r` |
| Modifica | `w` |
| Eliminazione | `w` |
| *(attraversamento)* | `x`, aggiunto automaticamente se c'è almeno un permesso |

Concedere un permesso esegue entrambi questi comandi:

```bash
setfacl -R -m  u:UTENTE:PERM  /percorso/cartella   # contenuti esistenti
setfacl -R -d -m u:UTENTE:PERM /percorso/cartella   # ACL di default → contenuti futuri
```

così i file e le cartelle creati in seguito ereditano gli stessi diritti.
Impostare un permesso diverso su una sottocartella sovrascrive l'ACL solo su
quel ramo: è così che funzionano gli override espliciti. **Applica (solo qui)**
scrive l'ACL su una sola cartella; **Applica (ricorsivo)** la propaga a
cascata.

> [!NOTE]
> **Perché Modifica ed Eliminazione condividono lo stesso bit.** Sui
> filesystem POSIX, cancellare un file dipende dal permesso di scrittura sulla
> *cartella che lo contiene*, non da un bit di delete sul singolo file come
> nelle ACL NTFS di Windows. Le due checkbox restano distinte nell'interfaccia
> e nel database — utile per l'audit e per future estensioni — ma a livello di
> filesystem si risolvono entrambe in `w`. Se vuoi che un utente modifichi i
> file senza poterli cancellare, le sole ACL POSIX non possono esprimerlo:
> servirebbe il livello VFS di Samba.

## La trappola di `force user`

Moltissime configurazioni Samba contengono questa riga:

```ini
[Dati]
    force user = smbuser
```

Fa sì che ogni connessione agisca sul filesystem come quell'unico utente,
indipendentemente da chi si è autenticato. Le ACL per utente non hanno quindi
**alcun effetto**: il filesystem non vede mai l'utente reale, quindi non c'è
nulla che l'ACL possa far corrispondere. È il motivo numero uno per cui si
conclude che «i permessi Samba non funzionano».

La dashboard lo rileva e propone una correzione in un clic, che:

1. fa un backup timestampato di `smb.conf`;
2. rimuove `force user` dalla condivisione gestita;
3. imposta `valid users = @smbgroup`;
4. valida il risultato con `testparm -s`, ripristinando il backup se fallisce;
5. ricarica Samba con `smbcontrol smbd reload-config`.

Non viene mai applicata automaticamente all'avvio: è un'azione esplicita e
reversibile dell'amministratore, e i backup restano in
`/etc/samba/smb.conf.bak-*`.

## Operazioni quotidiane

**Aggiornamento**

```bash
git pull
docker compose up -d --build
```

L'immagine viene ricostruita con il nuovo codice e i container ricreati. Utenti,
permessi e database Samba vivono in `./state/` e sopravvivono.

**Log**

```bash
docker compose logs -f
```

**Backup** — `./state/` è tutto ciò che conta. Tratta il backup come un
segreto: contiene copie di `/etc/shadow` e il database password di Samba.

```bash
docker compose stop
tar czf smb-backup-$(date +%F).tar.gz state/
docker compose start
```

**Ripristino** — ferma lo stack, sostituisci `state/`, riavvia.

## Alternativa: installazione diretta (LXC / VM)

Per chi fa già girare Samba nativamente e non vuole un container runtime.

```bash
cd /opt
git clone https://github.com/Andrea52-jimny/HomeLab-smbUserManager.git smb-user-manager
cd smb-user-manager
./install.sh          # come root
```

Lo script installa Samba, `acl` e Python; crea il gruppo di sistema
`smbgroup`; verifica e imposta `acltype=posixacl` sul dataset ZFS
corrispondente se `zfs` è disponibile; imposta i permessi di base sulla radice
della condivisione; crea il virtualenv; inizializza il database; installa e
avvia la unit systemd `smb-user-manager`.

```bash
systemctl status smb-user-manager
journalctl -u smb-user-manager -f
```

Per aggiornare: `git pull && systemctl restart smb-user-manager`.

## API

La web UI è un client leggero su un'API JSON. Ogni endpoint tranne `/login`
richiede un cookie di sessione. L'elenco completo è nel
[README inglese](README.md#api); la documentazione interattiva è su `/docs`
mentre l'app è in esecuzione.

## Struttura del progetto

```
.
├── app/                      pacchetto dell'applicazione FastAPI
│   ├── main.py               route
│   ├── config.py             configurazione da variabili d'ambiente
│   ├── database.py           schema SQLite e connessione
│   ├── auth.py               login admin, hashing bcrypt, sessioni
│   ├── samba_manager.py      useradd / smbpasswd / chage / deluser
│   ├── acl_manager.py        scansione cartelle dal vivo, setfacl / getfacl
│   └── smbconf_manager.py    riscrittura sicura di smb.conf
├── docker/
│   ├── entrypoint.sh         seed dello stato, avvio di smbd + uvicorn
│   ├── prepare-state.sh      crea ./state/ prima del primo avvio
│   └── smb.conf.default      configurazione iniziale
├── docs/                     architettura, configurazione, troubleshooting
├── static/  templates/       JavaScript vanilla e template Jinja2
├── Dockerfile  docker-compose.yml
├── install.sh  smb-user-manager.service     percorso senza Docker
└── init_db.py  requirements.txt
```

## Contribuire

Le issue che descrivono con cura un setup reale sono benvenute quanto le pull
request. Vedi [CONTRIBUTING.md](CONTRIBUTING.md) per l'ambiente di sviluppo e
le convenzioni — in particolare: niente `shell=True`, solo SQL
parametrizzato, e ogni percorso ricevuto dal client validato contro la radice
della condivisione.

## Sicurezza

Questa applicazione gira come root, gestisce utenti di sistema reali e vive in
un container privilegiato. Chiunque abbia una sessione ha di fatto root
sull'host Samba. Tienila sulla tua LAN o dietro una VPN, e leggi
[SECURITY.md](SECURITY.md) prima di metterla in produzione. Segnala le
vulnerabilità in privato tramite le security advisory di GitHub, non in una
issue pubblica.

## Licenza

[MIT](LICENSE) © Andrea

## Avvertenza

Questo software modifica utenti di sistema, `smb.conf` e ACL del filesystem.
Provalo su un dataset di prova prima di puntarlo su dati a cui tieni, e tieni
dei backup. È fornito così com'è, senza garanzie — vedi la licenza.
