# Sebasa Umbrel Community App Store

Community App Store para [Umbrel](https://umbrel.com) con la app **Mempool Bitcoin Watcher**.

## ➕ Cómo agregar esta tienda en Umbrel

1. Abre tu Umbrel → **App Store**
2. Haz clic en el ícono ⚙️ (esquina superior derecha)
3. En **Community App Stores**, pega esta URL:

```
https://github.com/sebasa/mempool-bitcoin-watcher
```

4. Haz clic en **Add** → aparecerá la tienda **"Sebasa Apps"**
5. Instala **Mempool Bitcoin Watcher** desde ahí
6. Accede a la interfaz web en el puerto **7890**

---

## 📦 Apps disponibles

### 🔍 Mempool Bitcoin Watcher (`sebasa-mempool-watcher`)

Monitor de transacciones Bitcoin via WebSocket usando tu nodo Mempool local.

**Características:**
- Monitoreo en tiempo real (WebSocket, sin polling)
- Categorías con webhooks y firma HMAC independientes
- Dashboard web: estadísticas, direcciones, categorías, TXs, log de webhooks
- Reconexión automática y sincronización sin reiniciar

**Puerto:** `7890`  
**Dependencia:** Mempool (debe estar instalado en Umbrel)

---

## 🛠 Desarrollo local

```bash
# Clonar el repo
git clone https://github.com/sebasa/mempool-bitcoin-watcher
cd mempool-bitcoin-watcher

# Build de la imagen
docker build -t mempool-watcher ./sebasa-mempool-watcher

# Correr localmente
docker run -d \
  -p 7890:7890 \
  -v $(pwd)/data:/data \
  -e MEMPOOL_URL=http://TU_IP_UMBREL:3006 \
  --name mempool-watcher \
  mempool-watcher

# Abrir UI
open http://localhost:7890
```

## 📂 Estructura del repositorio

```
/
├── umbrel-app-store.yml              ← Identifica el Community App Store
├── .github/
│   └── workflows/
│       └── docker-publish.yml       ← Build + push automático a GHCR
└── sebasa-mempool-watcher/          ← Carpeta de la app (id = sebasa-mempool-watcher)
    ├── umbrel-app.yml               ← Manifiesto: nombre, descripción, puerto, etc.
    ├── docker-compose.yml           ← Compose que usa Umbrel para instalar
    ├── exports.sh                   ← Variables de red internas de Umbrel
    ├── Dockerfile                   ← Imagen Docker
    ├── entrypoint.sh                ← Arranca watcher + web UI
    ├── watcher.py                   ← Servicio principal WebSocket
    ├── manage.py                    ← CLI de gestión
    ├── requirements.txt
    └── web/
        ├── app.py                   ← API Flask + servidor web
        └── templates/
            └── index.html           ← Dashboard UI
```

## 🔁 CI/CD

Cada push a `main` o nuevo tag `v*.*.*` dispara el workflow de GitHub Actions que:
1. Construye la imagen para `linux/amd64` y `linux/arm64` (Raspberry Pi)
2. La publica en `ghcr.io/sebasa/mempool-bitcoin-watcher`

La imagen publicada es la que usa el `docker-compose.yml` de Umbrel.
