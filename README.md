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
├── sebasa-btc-api/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── ...
├── sebasa-mempool-watcher/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   └── ...
├── sebasa-blockparser/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   └── ...
├── sebasa-criptosuite/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── index.html
│   └── tools/
└── sebasa-tidarr/
    ├── umbrel-app.yml
    └── docker-compose.yml
```

## How to Install on Umbrel

1. Push this repo to GitHub
2. In Umbrel, go to **App Store → ⋯ (three dots) → Community App Stores**
3. Paste your GitHub repo URL
4. Click **Add**
5. All apps will appear under **"Sebasa's Apps"**

## Notes on Image Publishing

Apps that use `build:` in docker-compose won't work on Umbrel — it only pulls pre-built images. If you update an app's source, rebuild and push to Docker Hub before installing:

    docker build -t sebasa/<app>:<version> <app-dir>/
    docker push sebasa/<app>:<version>

Then update the `image:` tag in the app's `docker-compose.yml`.

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

See [sebasa-criptosuite/README.md](sebasa-criptosuite/README.md) for image publishing instructions.

---

## Tidarr (`sebasa-tidarr`) — Port 7892

Web interface to download up to 24-bit/192 kHz media (tracks, albums, playlists, videos) from Tidal. Based on [cstaelen/tidarr](https://github.com/cstaelen/tidarr).
