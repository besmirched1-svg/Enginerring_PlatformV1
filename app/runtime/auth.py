import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("engine.runtime.auth")


class Role(Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


_ROLE_HIERARCHY: Dict[Role, int] = {
    Role.VIEWER: 0,
    Role.ENGINEER: 1,
    Role.ADMIN: 2,
}


def role_at_least(user_role: Role, required: Role) -> bool:
    return _ROLE_HIERARCHY.get(user_role, -1) >= _ROLE_HIERARCHY.get(required, 999)


@dataclass
class User:
    username: str
    role: Role = Role.VIEWER
    api_key: str = ""
    enabled: bool = True
    created_at: str = ""

    def __post_init__(self):
        if not self.api_key:
            self.api_key = _generate_key()
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Token:
    token: str
    username: str
    role: str
    expires_at: float
    issued_at: float = 0.0

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


def _generate_key(length: int = 32) -> str:
    return secrets.token_hex(length)


def _generate_jwt_like(payload: Dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded = _b64json(header) + "." + _b64json(payload)
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + sig


def _verify_jwt_like(token: str, secret: str) -> Optional[Dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    encoded = parts[0] + "." + parts[1]
    expected_sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts[2], expected_sig):
        return None
    try:
        payload = json.loads(_b64decode(parts[1]))
    except Exception:
        return None
    return payload


def _b64json(data: Dict[str, Any]) -> str:
    return _b64encode(json.dumps(data, separators=(",", ":")))


def _b64encode(s: str) -> str:
    import base64
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode()


def _b64decode(s: str) -> str:
    import base64
    padded = s + "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(padded).decode()


class AuthManager:
    def __init__(self, secret_key: str = "", users_file: str = ""):
        self._secret = secret_key or _generate_key(16)
        self._users_file = users_file or os.path.join(
            os.getenv("ENGINEERING_DATA_DIR", "outputs"), "auth", "users.json"
        )
        self._lock = threading.Lock()
        self._users: Dict[str, User] = {}
        self._tokens: Dict[str, Token] = {}
        self._load_users()

    def _users_path(self) -> str:
        return os.path.abspath(self._users_file)

    def _load_users(self) -> None:
        path = self._users_path()
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for entry in data:
                    try:
                        role = Role(entry.get("role", "viewer"))
                    except ValueError:
                        role = Role.VIEWER
                    user = User(
                        username=entry["username"],
                        role=role,
                        api_key=entry.get("api_key", _generate_key()),
                        enabled=entry.get("enabled", True),
                        created_at=entry.get("created_at", ""),
                    )
                    self._users[user.username] = user
                logger.info("Loaded %d users from %s", len(self._users), path)
            except Exception as exc:
                logger.warning("Could not load users: %s", exc)

    def _save_users(self) -> None:
        path = self._users_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = []
        for u in self._users.values():
            data.append({
                "username": u.username,
                "role": u.role.value,
                "api_key": u.api_key,
                "enabled": u.enabled,
                "created_at": u.created_at,
            })
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def add_user(self, username: str, role: Role = Role.VIEWER) -> User:
        with self._lock:
            if username in self._users:
                raise ValueError(f"User already exists: {username}")
            user = User(username=username, role=role)
            self._users[username] = user
            self._save_users()
            logger.info("Added user %s with role %s", username, role.value)
            return user

    def remove_user(self, username: str) -> bool:
        with self._lock:
            if username not in self._users:
                return False
            del self._users[username]
            self._save_users()
            logger.info("Removed user %s", username)
            return True

    def get_user(self, username: str) -> Optional[User]:
        return self._users.get(username)

    def list_users(self) -> List[User]:
        return list(self._users.values())

    def authenticate_api_key(self, api_key: str) -> Optional[User]:
        for u in self._users.values():
            if u.enabled and u.api_key == api_key:
                return u
        return None

    def create_token(self, username: str, ttl_seconds: float = 3600) -> Optional[Token]:
        with self._lock:
            user = self._users.get(username)
            if not user or not user.enabled:
                return None
            issued = time.time()
            expires = issued + ttl_seconds
            payload = {
                "sub": username,
                "role": user.role.value,
                "iat": issued,
                "exp": expires,
            }
            token_str = _generate_jwt_like(payload, self._secret)
            token = Token(
                token=token_str,
                username=username,
                role=user.role.value,
                expires_at=expires,
                issued_at=issued,
            )
            self._tokens[token_str] = token
            return token

    def validate_token(self, token_str: str) -> Optional[Dict[str, Any]]:
        payload = _verify_jwt_like(token_str, self._secret)
        if payload is None:
            return None
        if time.time() > payload.get("exp", 0):
            return None
        username = payload.get("sub", "")
        user = self._users.get(username)
        if not user or not user.enabled:
            return None
        return payload

    def check_permission(self, username: str, required_role: Role) -> bool:
        user = self._users.get(username)
        if not user or not user.enabled:
            return False
        return role_at_least(user.role, required_role)


_auth_instance: Optional[AuthManager] = None
_auth_lock = threading.Lock()


def get_auth_manager() -> AuthManager:
    global _auth_instance
    if _auth_instance is None:
        with _auth_lock:
            if _auth_instance is None:
                _auth_instance = AuthManager()
    return _auth_instance


def reset_auth_manager() -> None:
    global _auth_instance
    _auth_instance = None
