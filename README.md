# Sebasa's Apps — Umbrel Community App Store

Community App Store for Umbrel with Bitcoin tools and media apps.

## Apps

| App | Port | Description |
|-----|------|-------------|
| **sebasa-btc-api** | 7891 | Lightweight REST API for your Bitcoin node + Mempool |
| **sebasa-mempool-watcher** | 7890 | Real-time Bitcoin address monitor with webhook alerts |
| **sebasa-blockparser** | 7899 | Export raw blockchain data to CSV (rusty-blockparser GUI) |
| **sebasa-criptosuite** | 8777 | Bitcoin offline tools suite in isolated iframes |
| **sebasa-tidarr** | 7892 | Self-hosted Tidal media downloader with web UI |

## Repo Structure

```
umbrel-appstore/
├── umbrel-app-store.yml          ← Store manifest (id: sebasa)
├── README.md
├── .github/workflows/
│   └── release.yml               ← Automatic releases (see below)
├── sebasa-btc-api/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── icon.png
│   └── ...
├── sebasa-mempool-watcher/       ← own image (GHCR)
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── icon.svg
│   └── ...
├── sebasa-blockparser/           ← own image (Docker Hub)
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── icon.svg
│   └── backend/
├── sebasa-criptosuite/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile                ← local use only
│   ├── icon.svg
│   ├── index.html
│   └── tools/
└── sebasa-tidarr/
    ├── umbrel-app.yml
    ├── docker-compose.yml
    └── icon.svg
```

## How to Install on Umbrel

1. Push this repo to GitHub
2. In Umbrel, go to **App Store → ⋯ (three dots) → Community App Stores**
3. Paste your GitHub repo URL
4. Click **Add**
5. All apps will appear under **"Sebasa's Apps"**

## Releases (automatic)

**TL;DR:** edit an app, commit, push to `main`. No tags, no manual version bumps, no
`docker build`. The **Release apps** workflow
([.github/workflows/release.yml](.github/workflows/release.yml)) takes care of the rest.

### What happens on each push

The workflow looks at which `sebasa-*/` folders changed in the push and handles each app:

| App | Image | What the workflow does |
|-----|-------|------------------------|
| `sebasa-blockparser` | own — `sebasa/blockparser-gui` (Docker Hub) | Builds `linux/amd64` + `linux/arm64`, pushes `<version>` + `latest`, pins it in `docker-compose.yml`, bumps `version` |
| `sebasa-mempool-watcher` | own — `ghcr.io/sebasa/mempool-bitcoin-watcher` (GHCR) | Same as above |
| `sebasa-btc-api` | third-party (`python`) | Bumps `version` only |
| `sebasa-criptosuite` | third-party (`nginx`) | Bumps `version` only |
| `sebasa-tidarr` | third-party (`cstaelen/tidarr`) | Bumps `version` only |

Rules:

- **Version:** the patch number goes up (`1.0.4` → `1.0.5`). If you already changed `version`
  in `umbrel-app.yml` in that push, your value is kept.
- **Image build:** only when files other than `umbrel-app.yml` / `docker-compose.yml` changed
  (i.e. the actual code or `Dockerfile`). Editing only the compose just bumps the version.
- **Ignored:** changes that touch only `README.md` or `icon.*` don't trigger a release.
- **One commit:** all version bumps and image pins land in a single `github-actions[bot]`
  commit (`release: sebasa-blockparser 1.0.5, …`), so Umbrel only sees a new version once its
  image actually exists. Pins use `image: <name>:<version>@sha256:<digest>`.

Example: a push that changes `sebasa-criptosuite/index.html` and
`sebasa-blockparser/backend/main.py` ends with criptosuite at `1.2.1` and blockparser rebuilt
and at `1.0.5`, in one bot commit.

> **Tip:** for the apps with their own image, don't bump `version` by hand — if you do, Umbrel
> may see the new version a few minutes before the image is ready.

> **After every release, run `git pull`** before your next push: the bot commits to `main`.

### One-time setup

1. **Docker Hub secrets** (needed for `sebasa-blockparser`). In Docker Hub go to
   *Account settings → Personal access tokens* and create a token with *Read & Write*. Then in
   GitHub go to *Settings → Secrets and variables → Actions → New repository secret* and add:
   - `DOCKERHUB_USERNAME` — your Docker Hub user (`sebasa`)
   - `DOCKERHUB_TOKEN` — the token you just created

   GHCR (`sebasa-mempool-watcher`) uses the built-in `GITHUB_TOKEN`, nothing to configure.
2. **First release** (pins the images that existed before this workflow). Go to
   *Actions → Release apps → Run workflow* and run it twice, leaving *version* empty:
   - `sebasa-blockparser` → `1.0.5`, first multi-arch image
   - `sebasa-mempool-watcher` → `1.2.1`, stops using `:latest`

### Running it by hand

*Actions → Release apps → Run workflow*:

- **app**: the app folder, e.g. `sebasa-blockparser`
- **version**: optional; empty bumps the patch, or set e.g. `2.0.0`

Useful to force a rebuild (e.g. to pick up a new base image) or to jump a minor/major version.
A manual run always rebuilds apps that have their own image.

### Adding an app with its own image

1. Create the folder with `umbrel-app.yml`, `docker-compose.yml` (using `image:`, never
   `build:`) and a `Dockerfile` at its root (the folder is the build context).
2. Add a line to `image_for()` in [release.yml](.github/workflows/release.yml), using the image
   name exactly as written in `docker-compose.yml`:

       sebasa-myapp) echo "sebasa/myapp" ;;               # Docker Hub
       sebasa-myapp) echo "ghcr.io/sebasa/myapp" ;;       # GHCR

3. Push and run the workflow once by hand for that app.

Apps without their own image need nothing: they're picked up automatically.

> **GHCR:** the first time a new GHCR image is pushed it's created as **private**. Make it
> public in *GitHub → Packages → <image> → Package settings → Change visibility*, or Umbrel
> won't be able to pull it.

### Troubleshooting

- **The run fails at "Login Docker Hub"** → the secrets are missing or the token has expired.
- **`No encontré 'image: …'`** → the image name in `image_for()` doesn't match the one in
  `docker-compose.yml`.
- **Umbrel doesn't offer the update** → check that the bot commit is on `main` and that
  `version` changed in `umbrel-app.yml`; Umbrel only compares that field. The app store
  refreshes every few minutes.
- **`git push` rejected locally** → the bot pushed a release commit; `git pull --rebase` and
  push again.

---

## Bitcoin Node API (`sebasa-btc-api`) — Port 7891

FastAPI REST API connecting to your local Bitcoin Core and Mempool instances. All queries stay on-device — no third-party servers.

### Endpoints

#### Node
- `GET /health` — Health check (Bitcoin Core + Mempool)

#### Address
- `GET /address/{addr}` — Balance & tx count
- `GET /address/{addr}/utxos` — Unspent outputs
- `GET /address/{addr}/txs` — Transaction history

#### Transactions
- `GET /tx/{txid}` — Transaction details
- `GET /tx/{txid}/hex` — Raw transaction hex
- `GET /tx/{txid}/rsz` — Extract R, S, Z, pubkey per input
- `POST /tx/broadcast` — Broadcast raw tx `{"hex": "..."}`

#### Sweep
- `POST /sweep/wif` — Sweep from WIF key `{"key": "..."}`
- `POST /sweep/hex` — Sweep from hex key `{"key": "..."}`

---

## Mempool Bitcoin Watcher (`sebasa-mempool-watcher`) — Port 7890

Real-time address monitoring via WebSocket to your local Mempool node. Fires webhooks instantly when watched addresses send or receive funds.

- Group addresses into categories with independent webhook URLs and HMAC secrets
- Full transaction history and webhook delivery log in the web dashboard
- Zero-polling — pure WebSocket, no heavy interval queries

---

## Blockparser GUI (`sebasa-blockparser`) — Port 7899

Web GUI over rusty-blockparser (fork sebasa/blockparser 0.12.5). Reads `blk*.dat` files directly from your Bitcoin node and exports to CSV.

Available callbacks (lightweight, designed for Raspberry Pi 8 GB):
- `simplestats` — chain statistics
- `opreturn` — OP_RETURN payloads decoded as UTF-8
- `sigdump` — ECDSA signatures, public keys and message hashes
- `csvdump` — full blockchain export to CSV

> `unspentcsvdump` and `balances` are disabled — they require ~18 GB RAM.

---

## Cripto Suite Bitcoin (`sebasa-criptosuite`) — Port 8777

Bitcoin open-source tools running unmodified, each in its own `<iframe sandbox>`:

| Tool | Project |
|------|---------|
| BIP39 / HD Wallets | iancoleman/bip39 |
| WarpWallet | keybase/warpwallet |
| Wallet / TX Builder | OutCast3k/coinbin |
| Message Signing | ReinProject/bitcoin-signature-tool |
| Paper Wallet | pointbiz/bitaddress.org |
| Advanced Mnemonic | bitaps-com/mnemonic-offline-tool |

On Umbrel it runs on the official multi-arch `nginx` image and serves `index.html` + `tools/` straight from the app folder, so no custom image needs to be published. See [sebasa-criptosuite/README.md](sebasa-criptosuite/README.md) for local usage.

---

## Tidarr (`sebasa-tidarr`) — Port 7892

Web interface to download up to 24-bit/192 kHz media (tracks, albums, playlists, videos) from Tidal. Based on [cstaelen/tidarr](https://github.com/cstaelen/tidarr).
