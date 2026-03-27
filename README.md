# Sebasa's Apps — Umbrel Community App Store

Community App Store for Umbrel with Bitcoin tools and media apps.

## Apps

| App | Port | Description |
|-----|------|-------------|
| **sebasa-btc-api** | 8000 | FastAPI REST API for your Bitcoin node + Mempool |
| **sebasa-mempool-watcher** | 8001 | Mempool activity monitor |
| **sebasa-tidarr** | 8484 | Self-hosted Tidal media downloader with web UI |

## Repo Structure

```
umbrel-mempool-watcher/
├── umbrel-app-store.yml              ← Store manifest (id: sebasa)
├── README.md
├── sebasa-btc-api/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── sebasa-mempool-watcher/
│   ├── umbrel-app.yml
│   ├── docker-compose.yml
│   └── ...your existing files...
└── sebasa-tidarr/
    ├── umbrel-app.yml
    └── docker-compose.yml            ← Uses cstaelen/tidarr Docker Hub image
```

## How to Install on Umbrel

1. Push this repo to GitHub
2. In Umbrel, go to **App Store → ⋯ (three dots) → Community App Stores**
3. Paste your GitHub repo URL
4. Click **Add**
5. All three apps will appear under **"Sebasa's Apps"**

## Tidarr Setup

After installing Tidarr from the app store:

1. Open `http://umbrel.local:8484`
2. Authenticate your Tidal account through the UI token dialog
3. Configure download quality in settings
4. Downloads are saved to `/home/umbrel/media/music` by default

Tidarr supports optional integrations with Plex, Jellyfin, Navidrome, Beets, Lidarr,
and push notifications (Gotify, Ntfy). Configure these via environment variables in
the docker-compose.yml file.

## BTC API Endpoints

### Node Info
- `GET /info` — Node status, sync progress, connections
- `GET /blockheight` — Current block height
- `GET /health` — Health check (node + mempool)

### Fees (via Mempool)
- `GET /fees/recommended` — Recommended fee rates
- `GET /fees/mempool` — Fee distribution

### Address
- `GET /address/{addr}` — Balance & tx count
- `GET /address/{addr}/utxos` — Unspent outputs
- `GET /address/{addr}/txs` — Transaction history

### Transactions
- `GET /tx/{txid}` — Transaction details
- `GET /tx/{txid}/hex` — Raw transaction hex
- `GET /tx/{txid}/rsz` — Extract R, S, Z, pubkey per input
- `POST /tx/broadcast` — Broadcast raw tx `{"hex": "..."}`

### Sweep
- `POST /sweep/wif` — Sweep from WIF key `{"key": "..."}`
- `POST /sweep/hex` — Sweep from hex key `{"key": "..."}`

### Mempool
- `GET /mempool` — Mempool stats from node
- `GET /mempool/recent` — Recent mempool txs

API docs: `http://umbrel.local:8000/docs`
