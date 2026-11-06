# Temp Music (`sebasa-tempmusic`) — puerto 7893

Pegás un link y la app corre la herramienta que corresponde con tu configuración:

| Link | Herramienta |
|------|-------------|
| beatport.com / beatsource.com | [beatportdl](https://github.com/unspok3n/beatportdl) |
| tidal.com | [tidaler](https://pypi.org/project/tidaler/) (fork mantenido de tidal-dl-ng; el paquete original ya no está en PyPI) |
| todo lo demás | yt-dlp |

Cada descarga queda en su carpeta y se **borra sola a las 24 h** (revisión cada 5 min). Se baja archivo por archivo o todo junto en `.zip`.

## Dónde se editan las credenciales

Todo desde la propia app → **Ajustes**:

- **Beatport:** primer cuadro, `username:` y `password:` (archivo `beatportdl-config.yml`). Una vez guardada, la contraseña no vuelve a mostrarse (aparece como `********`; si la dejás así se conserva la guardada).
- **Tidal:** botón **Iniciar sesión en Tidal** → abrís el link, iniciás sesión, y pegás la URL de la página «Oops» donde terminás. El token queda guardado; no hay usuario/clave que guardar. Calidad y plantillas de nombre están en el cuadro *Opciones de Tidal* (`quality_audio`: `LOW`, `HIGH`, `LOSSLESS`, `HI_RES_LOSSLESS`).
- **yt-dlp:** cuadro `yt-dlp.conf`, una opción por línea.

En disco viven en `${APP_DATA_DIR}/data/app/config/` dentro del Umbrel (`beatportdl-config.yml`, `yt-dlp.conf`, `tidaler/settings.json`, `tidaler/token.json`).

## Acceso y túnel de Cloudflare

La app tiene **login propio** y desactiva el login de Umbrel (`PROXY_AUTH_ADD: "false"`), para poder publicarla. La contraseña es la que Umbrel genera para la app (se ve en la tarjeta de la app); si preferís otra, definí `ACCESS_PASSWORD` en el `docker-compose.yml`. Sin contraseña la app queda bloqueada.

Para publicarla, en Cloudflare Zero Trust → Networks → Tunnels, agregá un *Public hostname* con servicio `http://<ip-de-tu-umbrel>:7893` (o `http://localhost:7893` si `cloudflared` corre en el mismo Umbrel). Recomendado: poné además una política de **Cloudflare Access** delante, porque la app guarda tus credenciales de Beatport y Tidal.

## Notas

- Las descargas de Beatport y de Tidal se hacen de a una (comparten carpeta/config); yt-dlp corre hasta 2 en paralelo (`MAX_PARALLEL_JOBS`).
- yt-dlp y tidaler se actualizan solos en cada arranque (yt-dlp también desde Ajustes).
- Imagen propia en GHCR: el workflow *Release apps* la construye y fija el digest. La primera vez, hacé el paquete público en GitHub → Packages.
