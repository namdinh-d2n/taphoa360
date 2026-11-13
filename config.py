"""Load project-local configuration without overriding process environment variables."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {'1', 'true', 'yes', 'on', '0', 'false', 'no', 'off'}:
        raise ValueError(f'{name} must be true or false')
    return value in {'1', 'true', 'yes', 'on'}


APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
if APP_ENV not in {'development', 'production', 'test'}:
    raise ValueError('APP_ENV must be development, production, or test')
PRODUCTION = APP_ENV == 'production'
SEED_DEMO = env_bool('SEED_DEMO', not PRODUCTION)
COOKIE_SECURE = env_bool('COOKIE_SECURE', PRODUCTION)
ENABLE_DOCS = env_bool('ENABLE_DOCS', not PRODUCTION)
SETUP_TOKEN = os.getenv('SETUP_TOKEN', '')
_production_hosts = 'localhost,127.0.0.1,[::1]'
ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', _production_hosts if PRODUCTION else '*').split(',') if host.strip()]
PUBLIC_ORIGIN = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
if PUBLIC_ORIGIN:
    _origin = urlsplit(PUBLIC_ORIGIN)
    if (_origin.scheme not in {'http', 'https'} or not _origin.hostname or _origin.path
            or _origin.query or _origin.fragment or _origin.username or _origin.password
            or (PRODUCTION and (_origin.scheme != 'https' or _origin.hostname not in ALLOWED_HOSTS))):
        raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin with a hostname in ALLOWED_HOSTS for production')
MAX_REQUEST_BYTES = 1_048_576

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
RELOAD = env_bool('RELOAD', not PRODUCTION)
if PRODUCTION and (RELOAD or SEED_DEMO or not COOKIE_SECURE or '*' in ALLOWED_HOSTS):
    raise ValueError('Production requires RELOAD=false, SEED_DEMO=false, COOKIE_SECURE=true and explicit ALLOWED_HOSTS')

DB_TYPE = os.getenv("DB_TYPE", "sqlite").strip().lower()
if DB_TYPE not in {"sqlite", "mysql", "auto"}:
    raise ValueError("DB_TYPE must be sqlite, mysql, or auto")

MYSQL_HOST = os.getenv("DB_HOST", "127.0.0.1")
MYSQL_USER = os.getenv("DB_USER", "root")
MYSQL_PASS = os.getenv("DB_PASS", "")
MYSQL_NAME = os.getenv("DB_NAME", "taphoa360_db")
MYSQL_PORT = int(os.getenv("DB_PORT", "3306"))

_sqlite_path = Path(os.getenv("SQLITE_PATH", ".local/taphoa360.db"))
SQLITE_PATH = str((_sqlite_path if _sqlite_path.is_absolute() else BASE_DIR / _sqlite_path).resolve())
SQLITE_JOURNAL_MODE = os.getenv('SQLITE_JOURNAL_MODE', 'WAL').upper()
if SQLITE_JOURNAL_MODE not in {'WAL', 'DELETE'}:
    raise ValueError('SQLITE_JOURNAL_MODE must be WAL or DELETE')
