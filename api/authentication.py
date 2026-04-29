import json
from datetime import datetime, timedelta, timezone

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

try:
    import jwt
    def encode_jwt(payload):
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    def decode_jwt(token):
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
except ImportError:
    # Fallback: use python-jose
    from jose import jwt, JWTError
    def encode_jwt(payload):
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    def decode_jwt(token):
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def create_token(username: str) -> str:
    expiry = datetime.now(tz=timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)
    payload = {"sub": username, "exp": expiry}
    token = encode_jwt(payload)
    return token if isinstance(token, str) else token.decode()


def verify_token(token: str) -> str:
    """Decode token and return username, or raise AuthenticationFailed."""
    try:
        payload = decode_jwt(token)
        username = payload.get("sub")
        if not username:
            raise AuthenticationFailed("Invalid token payload.")
        return username
    except Exception:
        raise AuthenticationFailed("Invalid or expired token.")


def load_users():
    users_file = settings.USERS_FILE
    if users_file.exists():
        return json.loads(users_file.read_text())
    return {}


def save_users(users):
    settings.USERS_FILE.write_text(json.dumps(users, indent=2))


def get_user(username: str):
    return load_users().get(username)


def _ensure_demo_user():
    """Create demo user on first startup."""
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    users_file = settings.USERS_FILE
    if not users_file.exists():
        users_file.write_text(json.dumps({
            "demo": {
                "username": "demo",
                "hashed_password": ph.hash("demo123"),
                "role": "editor",
            }
        }, indent=2))


_ensure_demo_user()


class FakeUser:
    """Lightweight user object for DRF (no DB)."""
    def __init__(self, username, role="viewer"):
        self.username = username
        self.role = role
        self.is_authenticated = True
        self.is_active = True


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        username = verify_token(token)
        user = get_user(username)
        if not user:
            raise AuthenticationFailed("User not found.")
        role = user.get("role", "viewer")
        return (FakeUser(username, role), token)
