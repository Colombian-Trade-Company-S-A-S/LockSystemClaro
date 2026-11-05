# Despliegue en Render

Dos servicios independientes más una base de datos PostgreSQL gestionada:

| Servicio            | Tipo                | Qué corre                            |
| ------------------- | ------------------- | ------------------------------------ |
| `lockingsystem-api` | Web Service (Docker) | Django + Gunicorn + Chromium         |
| `lockingsystem-web` | Static Site          | Build de Vite (`frontend/dist`)      |
| PostgreSQL          | Render Postgres      | Base de datos (ya creada)            |

Puedes crearlos desde el blueprint [`render.yaml`](render.yaml) (Render → *New* →
*Blueprint*) o a mano en el dashboard con los valores de abajo.

---

## Por qué Docker en el backend

La Device Lock API de WhaleTV **solo sabe desbloquear**. El bloqueo real se hace
manejando el portal web con Selenium, así que el contenedor necesita un
navegador. El runtime nativo de Python de Render no trae Chrome; la imagen
instala `chromium` + `chromium-driver` desde los repos de Debian, que garantizan
que navegador y driver tengan versiones compatibles.

`televisores/portal/selenium_sync.py` localiza ambos con `CHROME_BIN` y
`CHROMEDRIVER`, que el Dockerfile ya define.

---

## Backend — `lockingsystem-api`

**Configuración del servicio**

| Campo               | Valor                  |
| ------------------- | ---------------------- |
| Runtime             | Docker                 |
| Dockerfile Path     | `./backend/Dockerfile` |
| Docker Context      | `./backend`            |
| Health Check Path   | `/api/health/`         |
| Region              | La misma que la base de datos (Oregon) |
| Plan                | Standard o superior — ver *Memoria* |

**Variables de entorno**

| Variable                      | Valor                                                        |
| ----------------------------- | ------------------------------------------------------------ |
| `DEBUG`                       | `False`                                                       |
| `SECRET_KEY`                  | Genérala en Render (*Generate*)                               |
| `JWT_SIGNING_KEY`             | Genérala en Render (*Generate*)                               |
| `DATABASE_URL`                | La **Internal Database URL** de tu Postgres                   |
| `DB_SCHEMA`                   | `LockClaro` — esquema propio dentro de esa base               |
| `CORS_ALLOWED_ORIGINS`        | URL del frontend, ej. `https://lockingsystem-web.onrender.com` |
| `CORS_ALLOW_ALL_ORIGINS`      | `False`                                                       |
| `FRONTEND_URL`                | URL del frontend — arma el enlace del correo de recuperación   |
| `SESSION_INACTIVITY_MINUTOS`  | `15` — minutos sin actividad antes de cerrar la sesión         |
| `GMAIL_CLIENT_ID`             | (secreto) OAuth de la cuenta remitente                        |
| `GMAIL_CLIENT_SECRET`         | (secreto)                                                     |
| `GMAIL_REFRESH_TOKEN`         | (secreto) con scope `gmail.send`                              |
| `GMAIL_FROM`                  | Cuenta remitente, la misma que autorizó el refresh token      |
| `WHALETV_LOCK_API_ACCESS_KEY` | (secreto)                                                     |
| `WHALETV_LOCK_API_SECRET_KEY` | (secreto)                                                     |
| `WHALETV_PORTAL_EMAIL`        | (secreto)                                                     |
| `WHALETV_PORTAL_PASSWORD`     | (secreto)                                                     |

No hace falta definir `ALLOWED_HOSTS` ni `CSRF_TRUSTED_ORIGINS`: `settings.py`
añade solo el dominio que Render publica en `RENDER_EXTERNAL_HOSTNAME`.

**Opcionales** (tienen valor por defecto; solo se definen para cambiarlo)

| Variable                | Por defecto | Para qué                                                       |
| ----------------------- | ----------- | -------------------------------------------------------------- |
| `PROXIES_DE_CONFIANZA`  | `1`         | Proxies delante de la app que añaden entrada a `X-Forwarded-For`. De aquí sale la IP de toda la auditoría, la sesión y la lista blanca de API-keys (`common/net.py`). Si tras un deploy todas las IP aparecen iguales, el número está mal. |
| `LOG_DIR`               | (vacío)     | Carpeta para guardar el log también en archivo, uno por día. En Render solo sirve con un disco persistente montado ahí. |
| `LOG_RETENCION_DIAS`    | `90`        | Días de log en archivo que se conservan (con `LOG_DIR`).        |

> **Usa la Internal Database URL**, no la externa. No sale a internet, es más
> rápida y no consume ancho de banda facturable. Requiere que el servicio esté
> en la misma región que la base de datos.

> **Esquema propio.** La instancia de Postgres la comparte la aplicación
> anterior (`whaletv`), cuyas tablas viven en `public`. Con `DB_SCHEMA` se fija
> el `search_path` de la conexión y esta app crea y consulta las suyas en
> `LockClaro`, sin tocar las otras. El esquema debe existir **antes** del primer
> `migrate`:
>
> ```sql
> CREATE SCHEMA IF NOT EXISTS "LockClaro";
> ```
>
> Si se omite `DB_SCHEMA`, Django cae en `public` y se mezclaría con las tablas
> antiguas. Las comillas importan: sin ellas Postgres pliega el nombre a
> minúsculas.

> **Correo y recuperación de contraseña.** El enlace que recibe el usuario se
> arma con `FRONTEND_URL`, así que debe apuntar al sitio estático, no al
> backend. El envío usa la API de Gmail con OAuth2
> ([`common/email_backend.py`](backend/common/email_backend.py)); el refresh
> token necesita el scope `gmail.send` — con `mail.google.com` también
> funcionaría, pero da acceso de lectura a todo el buzón y no hace falta. Sin
> las cuatro variables `GMAIL_*`, el arranque falla a propósito. En local, sin
> ellas, los correos se imprimen en la consola del `runserver`.
>
> El enlace vive `PASSWORD_RESET_MINUTOS` (10 por defecto) y es de un solo uso.

> **Sesión única.** Una cuenta solo puede tener una sesión abierta a la vez. Si
> alguien ya entró desde Chrome, otro navegador recibe un `409` al iniciar
> sesión y la sesión en curso no se interrumpe. Para desbloquear hay tres vías:
> cerrar sesión en el equipo original, esperar a que caduque por inactividad, o
> que un administrador la cierre desde **Usuarios** (también desde el admin de
> Django, borrando la fila en *Sesiones activas*). No hay variable de entorno:
> es una regla de negocio, no un ajuste.

> **Sesión por inactividad.** `SESSION_INACTIVITY_MINUTOS` (15 por defecto)
> acepta cualquier entero de minutos: 1, 2, 15, 20, 30… De ese valor se derivan
> las vidas de los JWT — el refresh token dura exactamente la ventana y el
> access un tercio (tope 5 min) — así que **el corte lo impone el servidor**, no
> solo el temporizador del navegador: copiar el refresh token de otro equipo no
> sirve pasada la ventana. El frontend lee el valor de `/api/config/` al
> arrancar, de modo que cambiarlo es reiniciar el backend, sin recompilar el
> sitio estático. Mientras el usuario interactúa, el cliente renueva el token y
> la ventana se reinicia sola.

**Arranque.** [`entrypoint.sh`](backend/entrypoint.sh) ejecuta `migrate` y
`collectstatic` antes de levantar Gunicorn. Se hace en runtime y no en el build
porque `settings.py` aborta con `DEBUG=False` si faltan los secretos de WhaleTV,
y durante el build de la imagen esas variables todavía no existen.

---

## Frontend — `lockingsystem-web`

| Campo               | Valor                  |
| ------------------- | ---------------------- |
| Runtime             | Static Site            |
| Root Directory      | `frontend`             |
| Build Command       | `npm ci && npm run build` |
| Publish Directory   | `dist`                 |

**Variable de entorno**

| Variable       | Valor                                       |
| -------------- | ------------------------------------------- |
| `VITE_API_URL` | `https://lockingsystem-api.onrender.com`    |

Sin `/api` al final: [`src/lib/config.ts`](frontend/src/lib/config.ts) ya añade
ese prefijo a cada endpoint. Definida en Render, esta variable **gana** sobre el
valor de `frontend/.env.production`.

**Rewrite obligatorio.** React Router resuelve las rutas en el cliente, así que
cualquier URL que no sea un fichero real debe devolver `index.html` — de lo
contrario recargar `/login` daría 404:

| Source | Destination    | Action  |
| ------ | -------------- | ------- |
| `/*`   | `/index.html`  | Rewrite |

Ya viene declarado en `render.yaml`.

---

## Orden de despliegue

1. Crea el backend. Anota su URL (`https://<nombre>.onrender.com`).
2. Crea el frontend con `VITE_API_URL` = URL del backend.
3. Vuelve al backend y pon `CORS_ALLOWED_ORIGINS` = URL del frontend.
4. Crea el superusuario:
   ```
   python manage.py createsuperuser
   ```
   desde la pestaña **Shell** del servicio en Render.

El primer despliegue del backend fallará si `CORS_ALLOWED_ORIGINS` aún no existe
—no pasa nada, el paso 3 lo arregla.

---

## Nota de despliegue: bitácora de auditoría

Este despliegue cambia la base de datos. `entrypoint.sh` aplica las migraciones
solo, al arrancar.

**Antes de desplegar**

1. Saca un backup de la base. La migración `televisores.0016` modifica filas
   existentes y no se puede deshacer.
2. Elige un momento sin lotes en curso: los trabajos en segundo plano mueren con
   el reinicio (ver *Deuda técnica*).

**Qué aplica `migrate`**

| Migración                  | Qué hace                                                        |
| -------------------------- | --------------------------------------------------------------- |
| `auditoria.0001`           | Tabla nueva `auditoria_evento` con sus índices                   |
| `televisores.0015`         | `SyncJob`: MAC, serial y `SET_NULL`; columna `api_key` en cuatro tablas |
| `televisores.0016`         | Copia MAC y serial del televisor a cada `SyncJob` existente      |

Referencia de duración: 8 s con 200.000 sincronizaciones, en un Postgres 17 local.
No hay variables nuevas obligatorias.

**Justo después de desplegar: comprobar `PROXIES_DE_CONFIANZA`**

El valor `1` no se puede confirmar sin desplegar, y de él salen la IP de la
auditoría, la regla de un navegador por cuenta y el límite de intentos. Si
está mal, usuarios distintos comparten IP y se bloquean entre sí.

1. Entra con una cuenta desde la oficina y con otra desde un celular con datos
   móviles.
2. En **Auditoría**, mira la IP de los dos inicios de sesión.
3. Cada una debe ser la IP pública de su red. Si coinciden y no es ninguna de las
   dos, pon `PROXIES_DE_CONFIANZA=2` en Render. Solo reinicia el servicio.

---

## Memoria: por qué no el plan gratuito

Cada Chromium headless consume unos **400 MB**. Los planes de 512 MB harán OOM
en cuanto arranque una sincronización. Además, el plan gratuito duerme el
servicio tras 15 minutos de inactividad.

`entrypoint.sh` arranca Gunicorn con 2 workers; cada uno puede abrir su propio
Chromium. Ajusta con estas variables si hace falta:

| Variable           | Defecto | Nota                                   |
| ------------------ | ------- | -------------------------------------- |
| `WEB_CONCURRENCY`  | `2`     | Workers. Más workers = más RAM.        |
| `GUNICORN_THREADS` | `4`     | Hilos por worker.                      |
| `GUNICORN_TIMEOUT` | `120`   | Las sincronizaciones tardan.           |

---

## Deuda técnica conocida

**Los jobs de sincronización corren en hilos daemon dentro del proceso web**
([`bulk_sync.py:175`](backend/televisores/bulk_sync.py#L175),
[`sync_runner.py:67`](backend/televisores/sync_runner.py#L67)).

Consecuencias:

- Si Render reinicia o redespliega el servicio, un job en curso **muere a
  medias** y queda en estado inconsistente en la base de datos.
- Los hilos no sobreviven al `--graceful-timeout` de 30 s de Gunicorn.
- No hay reintentos ni visibilidad de la cola.

Cuando esto empiece a doler, la solución es mover los jobs a un **Background
Worker** de Render con una cola real (Celery + Redis, o RQ). Es un refactor
aparte, no un ajuste de configuración.

---

## Desarrollo local

Nada de esto cambia el flujo local. Sin `DATABASE_URL` y con `DEBUG=True`, el
backend sigue usando SQLite y el frontend sigue usando el proxy de Vite.

```powershell
# Backend
cd backend; .\env\Scripts\Activate.ps1; python manage.py runserver

# Frontend
cd frontend; npm run dev
```

Con `DEBUG=False` y sin `DATABASE_URL`, el arranque falla a propósito: el disco
de un servicio en Render es efímero y un SQLite allí se borraría en cada
despliegue.

> **Si tu `backend/.env` define `DATABASE_URL`, apunta a esa base.** Para usar
> SQLite, déjala vacía en Git Bash: `DATABASE_URL= python manage.py test`. En
> PowerShell 5.1 **no sirve** `$env:DATABASE_URL=''`: borra la variable, y
> entonces `load_dotenv` carga la del `.env`.

**Pruebas contra Postgres.** SQLite no detecta todo: producción tiene columnas
`inet` y `jsonb`, que rechazan valores que SQLite acepta (ver
`auditoria/tests/test_datos_raros.py`). Antes de un despliegue con cambios en la
auditoría, corre la suite contra un Postgres local (Git Bash):

```bash
PG="/c/Program Files/PostgreSQL/17/bin"
"$PG/initdb.exe" -D /tmp/pgqa -U postgres --auth=trust --encoding=UTF8 --locale=C
"$PG/pg_ctl.exe" -D /tmp/pgqa -o "-p 55432" -l /tmp/pgqa.log -w start > /dev/null 2>&1 < /dev/null
"$PG/psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d template1 -c 'CREATE SCHEMA "LockClaro"'

DATABASE_URL=postgres://postgres@127.0.0.1:55432/postgres DB_SCHEMA=LockClaro \
  DATABASE_SSL_REQUIRE=False python manage.py test --noinput
```

La salida de `pg_ctl` se redirige a propósito: con un `|`, el comando no termina.
