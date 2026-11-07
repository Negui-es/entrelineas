import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


DEBUG = env_bool("DEBUG", True)
SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-before-deploying-entrelineas")
if not DEBUG and (SECRET_KEY.startswith(("development-", "REEMPLAZAR")) or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("Configura una SECRET_KEY aleatoria de al menos 50 caracteres.")
ALLOWED_HOSTS = [x.strip() for x in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "accounts", "library", "allauth", "allauth.account",
]
MIDDLEWARE = [
    "entrelineas.middleware.LocalAccessSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "entrelineas.localization.LegacyURLMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "entrelineas.middleware.PrivateResponseMiddleware",
]
ROOT_URLCONF = "entrelineas.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "library.context_processors.navigation",
        "entrelineas.localization.language_navigation",
    ]},
}]
WSGI_APPLICATION = "entrelineas.wsgi.application"
DATABASES = {"default": dj_database_url.config(
    default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60, conn_health_checks=True,
)}
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend", "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
REGISTRATION_OPEN = env_bool("REGISTRATION_OPEN", False)
CATALOG_USER_AGENT = os.getenv("CATALOG_USER_AGENT", "Entrelineas/0.1 (personal reading application)")
CATALOG_PREFERRED_LANGUAGE = os.getenv("CATALOG_PREFERRED_LANGUAGE", "es")
BOKTYVEN_API_TOKEN = os.getenv("BOKTYVEN_API_TOKEN", "").strip()
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
ACCOUNT_LOGIN_ON_PASSWORD_RESET = False
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_FORMS = {"signup": "accounts.forms.SignupForm", "login": "accounts.forms.LoginForm"}
ACCOUNT_ADAPTER = "accounts.adapter.AccountAdapter"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Entrelíneas] "
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "account_login"

# A database-backed cache shares authentication rate limits between Gunicorn workers.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "app_cache"}}
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 15
EMAIL_FILE_PATH = Path(os.getenv("EMAIL_FILE_PATH", BASE_DIR / "local-email"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Entrelíneas <noreply@localhost>")

LANGUAGE_CODE = "es"
LANGUAGES = [("es", "Español"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"), ("it", "Italiano")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Atlantic/Canary"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"catalog": {"format": "{asctime} {levelname} {message}", "style": "{"}},
    "handlers": {
        "request_errors": {"class": "logging.StreamHandler", "level": "ERROR"},
        "catalog_file": {"class": "logging.handlers.RotatingFileHandler", "filename": os.getenv("CATALOG_LOG_FILE", str(BASE_DIR / "catalog-debug.log")),
                         "maxBytes": 2_000_000, "backupCount": 3, "encoding": "utf-8", "delay": True,
                         "formatter": "catalog", "level": "WARNING"},
    },
    "loggers": {
        "django.request": {"handlers": ["request_errors"], "level": "ERROR", "propagate": False},
        "library.catalog": {"handlers": ["catalog_file"], "level": "WARNING", "propagate": False},
    },
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
X_FRAME_OPTIONS = "DENY"
# Enable only behind the supplied private container network / trusted reverse proxy.
if env_bool("TRUST_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
