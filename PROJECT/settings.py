import json
import sys
from pathlib import Path

from django.contrib.messages import constants as messages
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_FILE = BASE_DIR / 'secrets.json'


def load_secrets():
    try:
        with SECRETS_FILE.open(encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ImproperlyConfigured('Create secrets.json in project root (see secrets.example.json)') from exc


creds = load_secrets()


def get_secret(key, default=None):
    if key in creds:
        return creds[key]
    if default is not None:
        return default
    raise ImproperlyConfigured(f'Missing "{key}" in secrets.json')


SECRET_KEY = get_secret('SECRET_KEY')
DEBUG = get_secret('DEBUG', False)
ALLOWED_HOSTS = get_secret('ALLOWED_HOSTS', [])


def _build_default_csrf_trusted_origins(hosts):
    trusted_origins = []
    for host in hosts:
        host = str(host).strip()
        if not host or host == '*':
            continue
        if '://' in host:
            trusted_origins.append(host)
            continue
        trusted_origins.append(f'https://{host}')
        trusted_origins.append(f'http://{host}')
    return list(dict.fromkeys(trusted_origins))


CSRF_TRUSTED_ORIGINS = get_secret(
    'CSRF_TRUSTED_ORIGINS',
    _build_default_csrf_trusted_origins(ALLOWED_HOSTS),
)

if get_secret('USE_REVERSE_PROXY_SSL_HEADER', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Production is HTTPS-only, so never send the session or CSRF cookie over plain HTTP.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'widget_tweaks',
    'rest_framework',
    'apps.core',
    'apps.accounts',
    'apps.companies',
    'apps.content',
    'apps.studio',
    'apps.jobs',
    'apps.api',
    'apps.notifications',
    'apps.social',
    'apps.insights',
    'apps.whatsapp',
    'apps.inbox',
    'apps.ads',
    'apps.ops',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.core.middleware.LanguageMiddleware',
    'apps.accounts.middleware.PendingAccountMiddleware',
    'apps.companies.middleware.CurrentCompanyMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'PROJECT.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
                'django.template.context_processors.i18n',
                'apps.companies.context_processors.current_company',
                'apps.notifications.context_processors.notifications',
                'apps.ops.context_processors.ops',
            ],
        },
    },
]

WSGI_APPLICATION = 'PROJECT.wsgi.application'


# Database
DATABASES = {
    'default': get_secret('DATABASE')
}
# Local development may use SQLite; resolve its file relative to the project.
if DATABASES['default']['ENGINE'].endswith('sqlite3'):
    DATABASES['default']['NAME'] = str(BASE_DIR / DATABASES['default']['NAME'])

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'ar'
LANGUAGES = [
    ('ar', 'العربية'),
    ('en', 'English'),
]
# Arabic unless the user picked another language (saved on their account, or in this cookie before
# they sign in). The browser's language is deliberately ignored: many phones in our markets are set
# to English while their owners expect Arabic. See apps.core.middleware.LanguageMiddleware.
LANGUAGE_COOKIE_NAME = 'wakeel_lang'
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
LOCALE_PATHS = [BASE_DIR / 'locale']
# Server-side default only: every company works in its own timezone
# (see CurrentCompanyMiddleware).
TIME_ZONE = 'Asia/Qatar'
USE_I18N = True
USE_TZ = True


# Static & media files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
# Tests run without collectstatic, so they can't use the hashed manifest.
if 'test' in sys.argv:
    STORAGES['staticfiles']['BACKEND'] = 'django.contrib.staticfiles.storage.StaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# The design preview is shown in a same-origin iframe inside the post editor.
X_FRAME_OPTIONS = 'SAMEORIGIN'


# Authentication
AUTHENTICATION_BACKENDS = ['apps.accounts.backends.EmailOrUsernameBackend']
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'core:home'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_COOKIE_NAME = 'wakeel_sessionid'
CSRF_COOKIE_NAME = 'wakeel_csrftoken'

MESSAGE_TAGS = {
    messages.DEBUG: 'alert-secondary',
    messages.INFO: 'alert-info',
    messages.SUCCESS: 'alert-success',
    messages.WARNING: 'alert-warning',
    messages.ERROR: 'alert-danger',
}


# REST framework: the API is consumed by the app's own AJAX calls, so it
# rides on the session cookie (with CSRF) rather than tokens.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
}

# Public address of the site, used for links in emails (password reset,
# notifications) and for images that Meta must download when publishing.
SITE_URL = get_secret('SITE_URL', 'http://127.0.0.1:8000').rstrip('/')

# Email: SMTP when EMAIL_HOST is set, otherwise messages are printed to the console.
EMAIL_HOST = get_secret('EMAIL_HOST', '')
EMAIL_PORT = get_secret('EMAIL_PORT', 587)
EMAIL_HOST_USER = get_secret('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = get_secret('EMAIL_HOST_PASSWORD', '')
# Port 465 speaks SSL from the start (EMAIL_USE_SSL); port 587 upgrades with STARTTLS (EMAIL_USE_TLS).
EMAIL_USE_SSL = get_secret('EMAIL_USE_SSL', False)
EMAIL_USE_TLS = get_secret('EMAIL_USE_TLS', not EMAIL_USE_SSL) and not EMAIL_USE_SSL
EMAIL_TIMEOUT = 15
EMAIL_BACKEND = ('django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST
                 else 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = get_secret('DEFAULT_FROM_EMAIL', 'وكيل <no-reply@wakeel.local>')
# Shown on the terms and privacy pages: who provides Wakeel, in English and Arabic (left out when empty), and
# where subscribers reach a person, including data deletion requests.
LEGAL_ENTITY = get_secret('LEGAL_ENTITY', '')
LEGAL_ENTITY_AR = get_secret('LEGAL_ENTITY_AR', '') or LEGAL_ENTITY
SUPPORT_EMAIL = get_secret('SUPPORT_EMAIL', '')
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # 1 day

# Wakeel is a SaaS: anyone can sign up and create their own company workspace.
ALLOW_REGISTRATION = get_secret('ALLOW_REGISTRATION', True)


# AI: strategy, captions and rewrites all go through apps.ai.
# AI_PROVIDER picks the model vendor: 'anthropic' (Claude) or 'deepseek'.
AI_PROVIDER = get_secret('AI_PROVIDER', 'anthropic')
ANTHROPIC_API_KEY = get_secret('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = get_secret('ANTHROPIC_MODEL', 'claude-opus-5')
DEEPSEEK_API_KEY = get_secret('DEEPSEEK_API_KEY', '')
DEEPSEEK_MODEL = get_secret('DEEPSEEK_MODEL', 'deepseek-v4-pro')
DEEPSEEK_BASE_URL = get_secret('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
# DeepSeek charges less off-peak. The window, in UTC as [start, end], may cross midnight.
DEEPSEEK_OFF_PEAK_UTC = get_secret('DEEPSEEK_OFF_PEAK_UTC', ['16:30', '00:30'])
# Prices (USD per million tokens) for models other than DeepSeek, whose prices are built in (apps.ai.pricing).
# 0 means unknown: those calls show no cost.
AI_PRICE_INPUT_PER_MTOK = get_secret('AI_PRICE_INPUT_PER_MTOK', 0)
AI_PRICE_OUTPUT_PER_MTOK = get_secret('AI_PRICE_OUTPUT_PER_MTOK', 0)
AI_KEY_NAME = 'DEEPSEEK_API_KEY' if AI_PROVIDER == 'deepseek' else 'ANTHROPIC_API_KEY'
AI_ENABLED = bool(DEEPSEEK_API_KEY if AI_PROVIDER == 'deepseek' else ANTHROPIC_API_KEY)


# Direct publishing to Facebook and Instagram through a Meta app (developers.facebook.com).
# Its "Valid OAuth Redirect URI" must be SITE_URL + /company/social/meta/callback/.
META_APP_ID = get_secret('META_APP_ID', '')
META_APP_SECRET = get_secret('META_APP_SECRET', '')
META_GRAPH_VERSION = get_secret('META_GRAPH_VERSION', 'v23.0')
META_ENABLED = bool(META_APP_ID and META_APP_SECRET)
# Extra Meta permissions asked at connect time, off by default: Meta refuses the whole login dialog when it asks
# for a permission the app hasn't added. Add them to the Meta app (and pass app review), then list them here:
# analytics: ["read_insights", "instagram_manage_insights"];
# inbox: ["pages_read_user_content", "pages_manage_engagement", "instagram_manage_comments"].
# Without them publishing works, and engagement (likes, comments, shares) is still read.
META_INSIGHTS_SCOPES = get_secret('META_INSIGHTS_SCOPES', [])
META_INBOX_SCOPES = get_secret('META_INBOX_SCOPES', [])
# Paid promotion drafts (apps.ads). Off by default: set ["ads_management"] once the Meta app is approved for it.
META_ADS_SCOPES = get_secret('META_ADS_SCOPES', [])

# WhatsApp Business Cloud API, for client approvals (apps.whatsapp). Off until a token and number are set.
WHATSAPP_TOKEN = get_secret('WHATSAPP_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID = get_secret('WHATSAPP_PHONE_NUMBER_ID', '')
WHATSAPP_VERIFY_TOKEN = get_secret('WHATSAPP_VERIFY_TOKEN', '')
WHATSAPP_APP_SECRET = get_secret('WHATSAPP_APP_SECRET', '') or META_APP_SECRET
WHATSAPP_REVIEW_TEMPLATE = get_secret('WHATSAPP_REVIEW_TEMPLATE', 'wakeel_plan_review')
WHATSAPP_TEMPLATE_LANGUAGE = get_secret('WHATSAPP_TEMPLATE_LANGUAGE', 'ar')
WHATSAPP_ENABLED = bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID)

# TikTok app (developers.tiktok.com) with Login Kit and the Content Posting API (scope video.upload): designs are
# sent to the creator's TikTok inbox to finish posting. Its redirect URI must be SITE_URL + /company/social/tiktok/callback/
# (https only), and SITE_URL + /media/publish/ must be a verified URL prefix so TikTok can fetch the images.
TIKTOK_CLIENT_KEY = get_secret('TIKTOK_CLIENT_KEY', '')
TIKTOK_CLIENT_SECRET = get_secret('TIKTOK_CLIENT_SECRET', '')
TIKTOK_ENABLED = bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET)


# Design studio: post images are rendered from HTML templates by headless Chrome.
# Leave CHROME_PATH empty to use Playwright's own bundled Chromium.
CHROME_PATH = get_secret('CHROME_PATH', '')

# Web Push (installed app / browser notifications). Generate keys with `manage.py vapid_keys`.
VAPID_PUBLIC_KEY = get_secret('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = get_secret('VAPID_PRIVATE_KEY', '')
VAPID_SUBJECT = get_secret('VAPID_SUBJECT', 'mailto:no-reply@example.com')
PUSH_IN_BACKGROUND = 'test' not in sys.argv

# Backups (manage.py backup, run daily by a systemd timer in production). See apps.ops.backup.
BACKUP_DIR = get_secret('BACKUP_DIR', str(BASE_DIR.parent.parent / 'backups' / 'wakeel'))
BACKUP_KEEP_DAILY = get_secret('BACKUP_KEEP_DAILY', 7)
BACKUP_KEEP_WEEKLY = get_secret('BACKUP_KEEP_WEEKLY', 4)
BACKUP_MAX_GB = get_secret('BACKUP_MAX_GB', 20)          # never let backups grow past this
BACKUP_MIN_FREE_GB = get_secret('BACKUP_MIN_FREE_GB', 10)  # and always leave this much disk free

# Background worker (manage.py run_worker) poll interval, in seconds.
WORKER_POLL_SECONDS = 2
