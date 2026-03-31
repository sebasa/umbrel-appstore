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
```

## How to Install on Umbrel

1. Push this repo to GitHub
2. In Umbrel, go to **App Store → ⋯ (three dots) → Community App Stores**
3. Paste your GitHub repo URL
4. Click **Add**
5. All three apps will appear under **"Sebasa's Apps"**

## BTC API Endpoints

### Node Info
- `GET /health` — Health check (node + mempool)

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