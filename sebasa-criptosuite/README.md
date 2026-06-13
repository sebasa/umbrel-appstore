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

    docker-compose up -d           # construye y levanta en :8777
    PORT=9000 docker-compose up -d # puerto personalizado
    docker-compose up -d --build   # reconstruir tras cambios
    docker-compose down

## Uso local (sin Docker)

    python serve.py                # http://127.0.0.1:8777
    # o: python -m http.server 8777

No abrir `index.html` directamente con `file://`: Chrome bloquea subrecursos de iframes file://.

## Umbrel

La carpeta `umbrel/cripto-suite/` está lista para copiar al repositorio de tu app store:

    <tu-app-store>/
      umbrel-app-store.yml
      cripto-suite/               ← copiar esta carpeta
        umbrel-app.yml
        docker-compose.yml

El `docker-compose.yml` de Umbrel referencia una imagen publicada en un registro.
Para publicar la imagen desde este proyecto:

    docker build -t ghcr.io/tuusuario/cripto-suite:1.0.0 .
    docker push ghcr.io/tuusuario/cripto-suite:1.0.0

Luego reemplazar `youruser` en `umbrel/cripto-suite/docker-compose.yml` con tu usuario.

## Estructura del proyecto

    index.html                              shell (sidebar + iframes)
    Dockerfile                              nginx:alpine con los archivos
    docker-compose.yml                      levanta localmente (build local)
    serve.py                                alternativa sin Docker
    tools/
      bip39/                                iancoleman/bip39
      warpwallet-1.0.8/                     keybase/warpwallet
      coinbin/                              OutCast3k/coinbin
      bitcoin-signature-tool/              ReinProject/bitcoin-signature-tool
      bitaddress.org-3.3.0/               pointbiz/bitaddress.org
      mnemonic-offline-tool-master/        bitaps-com/mnemonic-offline-tool
    umbrel/
      cripto-suite/                         copiar al app store de Umbrel
        umbrel-app.yml
        docker-compose.yml

## Agregar otra herramienta

1. Copiar el proyecto en `tools/<nombre>/`
2. Agregar un `<button data-tool data-src>` y un `<iframe id="f-nombre">` en `index.html`
3. Extender el objeto `frames` en el script de `index.html`
4. Reconstruir: `docker-compose up -d --build`
