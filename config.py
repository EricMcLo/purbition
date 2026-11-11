import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Render persistent disk mount path
RENDER_DISK_PATH = Path('/opt/render/project/src/data')


def get_db_path():
    """Resolve database path for local vs Render."""
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('sqlite:///'):
        path_str = db_url.replace('sqlite:///', '')
        path = Path(path_str)
        # On Render: always use persistent disk absolute path
        if os.environ.get('RENDER') and not path.is_absolute():
            return RENDER_DISK_PATH / path.name
        # Local: use as-is (relative to project root)
        if not path.is_absolute():
            return BASE_DIR / path
        return path
    # Local fallback
    return BASE_DIR / 'database.db'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR / "database.db"}')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}