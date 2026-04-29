import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-dev-secret-key-123")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fallback-jwt-secret-123")

DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,.onrender.com").split(",")

INSTALLED_APPS = [
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'django.contrib.admin',  
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',        
    'django.contrib.messages',        
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
     'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  
    'django.contrib.messages.middleware.MessageMiddleware',    
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = "ffmpeg_studio.urls"

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  
                'django.contrib.auth.context_processors.auth', 
                'django.contrib.messages.context_processors.messages',  
            ],
        },
    },
]

WSGI_APPLICATION = "ffmpeg_studio.wsgi.application"

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

STATIC_URL = "/static/"

MEDIA_URL = "/"
MEDIA_ROOT = BASE_DIR

# CORS
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    os.environ.get("FRONTEND_URL", ""),
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "api.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# JWT
JWT_SECRET_KEY = "ffmpeg-studio-secret-change-in-production-xyz123"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# File storage
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
USERS_FILE = BASE_DIR / "users.json"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'