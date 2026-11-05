"""
Django settings for core project.

Proyecto: core (proyecto principal / raíz de la configuración).
Generado con Django 6.0.6 + Django REST Framework.
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carga variables de entorno desde el archivo .env (si existe).
load_dotenv(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-!quxor482@-*v$n_e@37!zk^)b(=*b9+c38et@zs-j%=ga-t2v',
)

# SECURITY WARNING: don't run with debug turned on in production!
# Apagado salvo que se pida (hallazgo H-18): un despliegue al que le falte la
# variable no debe quedar con trazas de error y datos internos a la vista. En
# local se enciende con DEBUG=True en backend/.env.
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()
]

# Render expone el dominio público del servicio en esta variable. Se añade solo
# para no tener que repetirlo a mano en ALLOWED_HOSTS en cada redespliegue.
RENDER_EXTERNAL_HOSTNAME = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Impide arrancar en producción con la clave de desarrollo insegura.
if not DEBUG and SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured(
        'Debes definir un SECRET_KEY seguro (variable de entorno SECRET_KEY) '
        'antes de ejecutar con DEBUG=False.'
    )


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Terceros
    'rest_framework',
    'corsheaders',

    # Apps locales
    'common',
    'users',
    'api',
    'televisores',
    'integracion',  # API-keys + API de integración (por serial)
    'auditoria',  # Bitácora central de eventos (plan de trazabilidad)
]

# Modelo de usuario personalizado (login por email, PK UUID).
AUTH_USER_MODEL = 'users.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise sirve los estáticos del admin/DRF sin depender de Nginx.
    # Debe ir inmediatamente después de SecurityMiddleware.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Huella de cada exportación a Excel y de los intentos denegados (H-07).
    'auditoria.middleware.AuditoriaExportacionesMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# SQLite en local; PostgreSQL en producción vía DATABASE_URL.
#
# OJO: el disco de un servicio web en Render es efímero — un SQLite allí se
# borraría en cada despliegue. En la nube DATABASE_URL es obligatoria.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # Espera si la BD está bloqueada (hilos de sincronización en 2º plano).
        'OPTIONS': {'timeout': 20},
    }
}

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    DATABASES['default'] = dj_database_url.parse(
        DATABASE_URL,
        # Reutiliza conexiones entre peticiones (Render cobra por conexión).
        conn_max_age=600,
        conn_health_checks=True,
        # El Postgres gestionado de Render exige TLS desde fuera de su red.
        ssl_require=os.getenv('DATABASE_SSL_REQUIRE', 'True') == 'True',
    )

    # La instancia de Postgres es compartida con la app antigua (whaletv), que
    # vive en `public`. Todo lo de esta app va a su propio esquema para que las
    # dos convivan sin pisarse: DB_SCHEMA fija el search_path de la conexión y
    # Django crea y consulta sus tablas ahí sin tocar `public`.
    #
    # El esquema debe existir antes de migrar:
    #   CREATE SCHEMA IF NOT EXISTS "LockClaro";
    DB_SCHEMA = os.getenv('DB_SCHEMA', '').strip()
    if DB_SCHEMA:
        # Comillas dobles: el nombre lleva mayúsculas y Postgres las plegaría
        # a minúsculas si fuera sin citar.
        DATABASES['default'].setdefault('OPTIONS', {})
        DATABASES['default']['OPTIONS']['options'] = f'-c search_path="{DB_SCHEMA}"'
elif not DEBUG:
    raise ImproperlyConfigured(
        'Falta DATABASE_URL. Con DEBUG=False no se puede usar SQLite: el disco '
        'del servicio es efímero y perderías los datos en cada despliegue.'
    )


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Hashing de contraseñas: Argon2 primero (recomendación OWASP), con PBKDF2 y
# bcrypt de respaldo para poder verificar hashes heredados y re-hashear.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'es-co'

TIME_ZONE = 'America/Bogota'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

# Destino de `collectstatic`. Solo contiene los estáticos del admin de Django y
# del navegador de DRF; el frontend React se despliega aparte.
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        # Comprime y versiona los estáticos (cache-busting por hash).
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Proxies de confianza (IP real del cliente)
# ---------------------------------------------------------------------------
# Nº de proxies delante de la app que AÑADEN una entrada a X-Forwarded-For. En
# Render se asume 1 (su balanceador); está sin confirmar con el proveedor
# (decisión D-1 del plan de trazabilidad), por eso es variable de entorno: si
# tras desplegar todas las IP salen iguales, se corrige aquí sin tocar código.
# Con 0 se ignora la cabecera y se usa la IP de la conexión. Ver common/net.py.
PROXIES_DE_CONFIANZA = int(os.getenv('PROXIES_DE_CONFIANZA', '1'))


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Sin esto DRF usa la cabecera X-Forwarded-For ENTERA como identidad del
    # throttle: cambiándola en cada intento se esquivaba el límite de login.
    'NUM_PROXIES': PROXIES_DE_CONFIANZA,
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # JWT con revocación server-side (logout real): ver users/authentication.py
        'users.authentication.RevocationAwareJWTAuthentication',
    ),
    # Secure-by-default: todo requiere autenticación salvo que la vista lo
    # abra explícitamente (registro, obtención de token) con AllowAny.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_FILTER_BACKENDS': (
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    # Rate limiting para mitigar abuso y fuerza bruta.
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/hour',
        'user': '1000/hour',
        'login': '5/min',      # obtención de token
        'register': '10/hour',  # alta de cuentas
        # Recuperación de contraseña: endpoint público que dispara correos. Un
        # límite bajo evita usarlo para inundar el buzón de alguien o para
        # sondear qué correos están registrados.
        'password_reset': '5/hour',
        'integracion': '2000/hour',  # API-key de integración (por clave)
    },
    # En producción se sirve solo JSON; el navegador de la API queda para dev.
    'DEFAULT_RENDERER_CLASSES': (
        ('rest_framework.renderers.JSONRenderer',)
        if not DEBUG
        else (
            'rest_framework.renderers.JSONRenderer',
            'rest_framework.renderers.BrowsableAPIRenderer',
        )
    ),
}

# ---------------------------------------------------------------------------
# Cierre de sesión por inactividad
# ---------------------------------------------------------------------------
# Minutos que puede estar el usuario sin interactuar antes de que se le cierre
# la sesión y vuelva al login. Vale cualquier entero de minutos: 1, 2, 15, 30…
SESSION_INACTIVITY_MINUTOS = max(
    1, int(os.getenv('SESSION_INACTIVITY_MINUTOS', '15'))
)

# La ventana se impone en el SERVIDOR haciendo que el refresh token dure
# exactamente eso. No basta con un temporizador en el navegador: eso solo
# esconde la interfaz, y quien copie el refresh token de localStorage seguiría
# entrando. Como `ROTATE_REFRESH_TOKENS` está activo, cada renovación entrega un
# refresh nuevo — mientras el usuario esté activo la ventana se reinicia sola, y
# en cuanto deja de estarlo el token muere solo.
_REFRESH_LIFETIME = timedelta(minutes=SESSION_INACTIVITY_MINUTOS)

# El access token tiene que vencer bastante antes que el refresh, o el cliente
# no llegaría a renovar dentro de la ventana. Un tercio deja dos oportunidades
# de renovación antes del corte; el tope de 5 min mantiene corta la exposición
# si un access se filtra, y el suelo de 20 s hace que ventanas de 1 minuto
# sigan funcionando.
_ACCESS_LIFETIME = max(
    timedelta(seconds=20),
    min(timedelta(minutes=5), _REFRESH_LIFETIME / 3),
)


# ---------------------------------------------------------------------------
# Simple JWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    # Vidas derivadas de la ventana de inactividad (ver arriba).
    'ACCESS_TOKEN_LIFETIME': _ACCESS_LIFETIME,
    'REFRESH_TOKEN_LIFETIME': _REFRESH_LIFETIME,

    # Rotación de refresh: cada refresh entrega uno nuevo.
    'ROTATE_REFRESH_TOKENS': True,
    # Revocación total del refresh anterior. Requiere la app
    # 'rest_framework_simplejwt.token_blacklist' (ver nota de rutas largas en
    # Windows / SECURITY.md). Se deja en False hasta poder habilitarla.
    'BLACKLIST_AFTER_ROTATION': False,

    # Firma: HS256 con una clave dedicada (por defecto usa SECRET_KEY).
    'ALGORITHM': 'HS256',
    # `or SECRET_KEY` cubre el caso de una variable definida pero vacía.
    'SIGNING_KEY': os.getenv('JWT_SIGNING_KEY') or SECRET_KEY,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',

    # Registra el último acceso al obtener token (auditoría básica).
    'UPDATE_LAST_LOGIN': True,
}

# ---------------------------------------------------------------------------
# WhaleTV Device Lock API (Zeasn SaaS) — firma HMAC-SHA1
# ---------------------------------------------------------------------------
# Credenciales por entorno: DEV/ACC/PROD. Se leen SIEMPRE de variables de
# entorno (nunca hardcodeadas en el código) para poder rotarlas y para no
# versionar secretos. Definir en `.env` (claves documentadas en `README.md`).
WHALETV_LOCK_API = {
    'HOST': os.getenv('WHALETV_LOCK_API_HOST', 'saas.zeasn.tv'),
    'ACCESS_KEY': os.getenv('WHALETV_LOCK_API_ACCESS_KEY', ''),
    'SECRET_KEY': os.getenv('WHALETV_LOCK_API_SECRET_KEY', ''),
    'API_BASE': os.getenv('WHALETV_LOCK_API_BASE', '/device-lock/api/v1'),
    'TIMEOUT': int(os.getenv('WHALETV_LOCK_API_TIMEOUT', '15')),
}

# ---------------------------------------------------------------------------
# WhaleTV Device Lock *Portal* API (Open API) — firma HMAC-SHA1
# ---------------------------------------------------------------------------
# OJO: es un servicio DISTINTO de WHALETV_LOCK_API de arriba, con credenciales
# propias. Es la API oficial del mismo portal web que hoy raspamos con Selenium
# (lockservice.whaletv.com), así que vive en el entorno correcto y —a diferencia
# de la Device Lock API— sí puede BLOQUEAR. Doc: "Device Lock Portal API 1.0.1".
#
# BRAND_ID es obligatorio en todos sus endpoints. Mientras no lo sepamos queda
# vacío y `manage.py probar_portal_open` lo descubre por tanteo.
WHALETV_LOCK_PORTAL_API = {
    # Encendido por defecto: la API es el camino normal porque es ~5 veces más
    # rápida y no necesita navegador. Selenium queda de respaldo automático para
    # cuando la API falle (ver televisores/portal/open_sync.py). Ponerlo en
    # `false` fuerza Selenium para todo, sin desplegar código.
    # Sólo se activa si además están las tres credenciales; ver `usa_open()`.
    'ENABLED': os.getenv('WHALETV_LOCK_PORTAL_API_ENABLED', 'true').lower() == 'true',
    'HOST': os.getenv(
        'WHALETV_LOCK_PORTAL_API_HOST', 'acc-lockservice.whaletv.com'
    ),
    'ACCESS_KEY': os.getenv('WHALETV_LOCK_PORTAL_API_ACCESS_KEY', ''),
    'SECRET_KEY': os.getenv('WHALETV_LOCK_PORTAL_API_SECRET_KEY', ''),
    'BRAND_ID': os.getenv('WHALETV_LOCK_PORTAL_API_BRAND_ID', ''),
    'API_BASE': os.getenv('WHALETV_LOCK_PORTAL_API_BASE', '/lock-portal/open/v1'),
    'TIMEOUT': int(os.getenv('WHALETV_LOCK_PORTAL_API_TIMEOUT', '20')),
}

# Correos con acceso al diagnóstico de la API (pantalla de Configuración).
# Es una herramienta de soporte, no una función del producto: enseña host,
# brandId y los mensajes crudos de WhaleTV. Lista separada por comas.
DIAGNOSTICO_API_EMAILS = {
    c.strip().lower()
    for c in os.getenv(
        'DIAGNOSTICO_API_EMAILS', 'palaciosjulian286@gmail.com'
    ).split(',')
    if c.strip()
}

# Minutos sin latido tras los que se da por muerto un job de sincronización
# (su hilo se fue con el proceso). Ver televisores/watchdog.py. Holgado a
# propósito: un sync individual tarda ~40 s y un lote late en cada televisor.
JOBS_TIMEOUT_MINUTOS = int(os.getenv('JOBS_TIMEOUT_MINUTOS', '10'))

# ---------------------------------------------------------------------------
# WhaleTV Portal (automatización web con Selenium) — permite BLOQUEAR/desbloquear
# ---------------------------------------------------------------------------
# La Device Lock API no puede bloquear; el bloqueo real se hace controlando el
# portal web (Lock Status + Next Installment Date). Credenciales por entorno.
WHALETV_PORTAL = {
    'LOGIN_URL': os.getenv(
        'WHALETV_PORTAL_LOGIN_URL', 'https://lockservice.whaletv.com/login'
    ),
    'DEVICE_LIST_URL': os.getenv(
        'WHALETV_PORTAL_DEVICE_LIST_URL',
        'https://lockservice.whaletv.com/deviceManage/deviceList',
    ),
    'EMAIL': os.getenv('WHALETV_PORTAL_EMAIL', ''),
    'PASSWORD': os.getenv('WHALETV_PORTAL_PASSWORD', ''),
    'HEADLESS': os.getenv('WHALETV_PORTAL_HEADLESS', 'true').lower() == 'true',
    'TIMEOUT': int(os.getenv('WHALETV_PORTAL_TIMEOUT', '30')),
    # Suma/resta de días a hoy para la Next Installment Date (igual que whaletv).
    'DIAS_DESFASE': int(os.getenv('WHALETV_PORTAL_DIAS_DESFASE', '30')),
}

# En producción, exige que los secretos de integración estén definidos: evita
# desplegar con credenciales vacías (fallo silencioso) o dejarlas en el código.
if not DEBUG:
    # El portal es obligatorio siempre: es la única vía para bloquear, y en modo
    # portal también es de donde se lee todo (ver televisores/portal/proveedor.py).
    _faltantes = [
        nombre
        for nombre, valor in (
            ('WHALETV_PORTAL_EMAIL', WHALETV_PORTAL['EMAIL']),
            ('WHALETV_PORTAL_PASSWORD', WHALETV_PORTAL['PASSWORD']),
        )
        if not valor
    ]
    # Las llaves de la Device Lock API sí pueden faltar (modo portal), pero a
    # medias no: una sin la otra es una configuración rota que solo fallaría al
    # primer uso, y siempre firmando mal.
    _api = (WHALETV_LOCK_API['ACCESS_KEY'], WHALETV_LOCK_API['SECRET_KEY'])
    if any(_api) and not all(_api):
        _faltantes.append(
            'WHALETV_LOCK_API_ACCESS_KEY/SECRET_KEY (define las dos o ninguna)'
        )
    if _faltantes:
        raise ImproperlyConfigured(
            'Faltan secretos de integración WhaleTV en el entorno: '
            + ', '.join(_faltantes)
        )


# ---------------------------------------------------------------------------
# Correo saliente — Gmail con OAuth2
# ---------------------------------------------------------------------------
# Se usa para el enlace de recuperación de contraseña. La implementación está en
# common/email_backend.py (SMTP + XOAUTH2, sin dependencias extra).
GMAIL = {
    'CLIENT_ID': os.getenv('GMAIL_CLIENT_ID', ''),
    'CLIENT_SECRET': os.getenv('GMAIL_CLIENT_SECRET', ''),
    'REFRESH_TOKEN': os.getenv('GMAIL_REFRESH_TOKEN', ''),
    # Cuenta remitente. Debe ser la misma que autorizó el refresh token: Gmail
    # rechaza autenticarse como una cuenta distinta.
    'FROM': os.getenv('GMAIL_FROM', ''),
}

GMAIL_CONFIGURADO = all(GMAIL.values())

if GMAIL_CONFIGURADO:
    EMAIL_BACKEND = 'common.email_backend.GmailOAuth2EmailBackend'
elif DEBUG:
    # Sin credenciales en local, los correos se imprimen en la consola del
    # runserver: el flujo de recuperación se puede probar copiando el enlace.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    raise ImproperlyConfigured(
        'Faltan credenciales de Gmail (GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, '
        'GMAIL_REFRESH_TOKEN, GMAIL_FROM). Sin ellas la recuperación de '
        'contraseña no puede enviar correos.'
    )

DEFAULT_FROM_EMAIL = GMAIL['FROM'] or 'no-reply@localhost'
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Nombre que aparece en el correo y como remitente legible.
APP_NOMBRE = os.getenv('APP_NOMBRE', 'Locking System')

# Base pública del frontend: con ella se construye el enlace del correo. En
# local apunta al dev server de Vite; en Render, a la URL del sitio estático.
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173').rstrip('/')

# Vigencia del enlace de recuperación. Corta a propósito: el enlace llega por
# correo (un canal que puede quedar abierto en un equipo compartido) y además es
# de un solo uso — ver users/models.py, PasswordResetToken.
PASSWORD_RESET_MINUTOS = int(os.getenv('PASSWORD_RESET_MINUTOS', '10'))


# ---------------------------------------------------------------------------
# CORS  (allowlist explícita — nunca comodín en producción)
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = os.getenv('CORS_ALLOW_ALL_ORIGINS', 'False') == 'True'
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173',
    ).split(',') if o.strip()
]
# La autenticación viaja en el header Authorization (Bearer), no en cookies.
CORS_ALLOW_CREDENTIALS = False


# ---------------------------------------------------------------------------
# Seguridad HTTP
# ---------------------------------------------------------------------------
# Cabeceras/cookies que aplican en cualquier entorno.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
# Confía en el proxy inverso para detectar HTTPS (típico en despliegues).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Refuerzos que solo tienen sentido con HTTPS (producción).
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    # El health check interno de Render llega por HTTP y sin cabecera
    # X-Forwarded-Proto: sin esta exención recibiría un 301 y daría el servicio
    # por caído. El resto de rutas sí se fuerzan a HTTPS.
    SECURE_REDIRECT_EXEMPT = [r'^api/health/?$']
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Orígenes de confianza para CSRF (formularios del admin sobre HTTPS).
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
    ]
    if RENDER_EXTERNAL_HOSTNAME:
        _render_origin = f'https://{RENDER_EXTERNAL_HOSTNAME}'
        if _render_origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(_render_origin)


# ---------------------------------------------------------------------------
# Logging  (no registra cuerpos ni credenciales; útil para auditar seguridad)
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{levelname}] {asctime} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}

# Destino persistente del log (hallazgo H-11). Con LOG_DIR definida, además de
# la consola se escribe un archivo por día en esa carpeta y se borran los de más
# de LOG_RETENCION_DIAS días. Ver common/log_archivo.py.
#
# OJO en Render: el disco del servicio es efímero. Sin un disco persistente
# montado en LOG_DIR los archivos se pierden en cada deploy; ahí lo que conserva
# el log es un Log Stream de Render hacia un servicio externo (se configura en
# el dashboard, no en el código).
LOG_DIR = os.getenv('LOG_DIR', '').strip()
if LOG_DIR:
    LOGGING['handlers']['archivo'] = {
        'class': 'common.log_archivo.ArchivoDiarioHandler',
        'formatter': 'simple',
        'directorio': LOG_DIR,
        'retencion_dias': int(os.getenv('LOG_RETENCION_DIAS', '90')),
    }
    LOGGING['root']['handlers'].append('archivo')
    LOGGING['loggers']['django.security']['handlers'].append('archivo')
