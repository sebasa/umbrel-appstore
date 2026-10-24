# Cripto Suite Bitcoin

Herramientas Bitcoin open-source corriendo sin modificar, cada una en su propio `<iframe sandbox>`.

## Herramientas incluidas

| Pestaña | Proyecto | Función |
|---|---|---|
| BIP39 / HD | iancoleman/bip39 | Mnemónico → semilla → direcciones |
| WarpWallet | keybase/warpwallet | Cartera determinista (frase + sal, scrypt+PBKDF2) |
| Wallet / TX | OutCast3k/coinbin | Direcciones, multisig, TX, broadcast |
| Firmar mensajes | ReinProject/bitcoin-signature-tool | Firmar / verificar mensajes |
| Direcciones / Paper | pointbiz/bitaddress.org | Paper wallet, bulk, vanity, split |
| Mnemónico avanzado | bitaps-com/mnemonic-offline-tool | Dados, split/restore, XPUB, BIP44/49/84 |

## Uso local (Docker)

El `docker-compose.yml` referencia la imagen publicada en Docker Hub. Para correr localmente hay que construir primero:

    docker build -t sebasa/criptosuite:1.0.0 .
    docker-compose up -d           # levanta en :8777
    PORT=9000 docker-compose up -d # puerto personalizado
    docker-compose down

Para reconstruir tras cambios:

    docker build -t sebasa/criptosuite:1.0.0 .
    docker-compose up -d

## Uso local (sin Docker)

    python serve.py                # http://127.0.0.1:8777
    # o: python -m http.server 8777

No abrir `index.html` directamente con `file://`: Chrome bloquea subrecursos de iframes file://.

## Umbrel: sin imagen propia

Desde la versión 1.2.0 el `docker-compose.yml` usa la imagen oficial `nginx` (multi-arch,
amd64/arm64) y monta `index.html` y `tools/` desde `${APP_DATA_DIR}`, que es donde Umbrel
copia esta carpeta al instalar o actualizar la app. Para cambiar las herramientas alcanza
con commitear los archivos y subir la versión en `umbrel-app.yml`; no hace falta publicar
nada en Docker Hub. El `Dockerfile` queda sólo para uso local.

## Umbrel

La estructura del app store ya está lista:

    sebasa-criptosuite/
      umbrel-app.yml
      docker-compose.yml    ← usa image:, no build:
      index.html
      Dockerfile
      tools/

Para agregar al app store en Umbrel:

1. Publicar la imagen: `docker build + docker push` (ver arriba)
2. Agregar este repositorio como Community App Store en Umbrel
3. Instalar desde la tienda

## Estructura del proyecto

    index.html                              shell (sidebar + iframes)
    Dockerfile                              nginx:alpine con los archivos
    docker-compose.yml                      referencia imagen publicada (Umbrel / prod)
    serve.py                                alternativa sin Docker
    tools/
      bip39/                                iancoleman/bip39
      warpwallet-1.0.8/                     keybase/warpwallet
      coinbin/                              OutCast3k/coinbin
      bitcoin-signature-tool/              ReinProject/bitcoin-signature-tool
      bitaddress.org-3.3.0/               pointbiz/bitaddress.org
      mnemonic-offline-tool-master/        bitaps-com/mnemonic-offline-tool

## Agregar otra herramienta

1. Copiar el proyecto en `tools/<nombre>/`
2. Agregar un `<button data-tool data-src>` y un `<iframe id="f-nombre">` en `index.html`
3. Extender el objeto `frames` en el script de `index.html`
4. Reconstruir y republicar: `docker build -t sebasa/criptosuite:<nueva-version> . && docker push ...`
5. Actualizar el tag en `docker-compose.yml` y `umbrel-app.yml`
