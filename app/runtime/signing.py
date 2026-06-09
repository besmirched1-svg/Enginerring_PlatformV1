import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("engine.runtime.signing")


def _get_signing_key(key: Optional[str] = None) -> str:
    if key:
        return key
    env_key = os.getenv("ENGINEERING_SIGNING_KEY", "")
    if env_key:
        return env_key
    return "engineering-platform-default-signing-key"


def sign_data(data: Any, key: Optional[str] = None) -> str:
    signing_key = _get_signing_key(key)
    if isinstance(data, (dict, list)):
        raw = json.dumps(data, separators=(",", ":"), sort_keys=True)
    else:
        raw = str(data)
    return hmac.new(
        signing_key.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()


def verify_signature(data: Any, signature: str, key: Optional[str] = None) -> bool:
    expected = sign_data(data, key)
    return hmac.compare_digest(expected, signature)


def sign_file(file_path: str, key: Optional[str] = None) -> str:
    signing_key = _get_signing_key(key)
    h = hmac.new(signing_key.encode(), b"", hashlib.sha256)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_file(file_path: str, signature: str, key: Optional[str] = None) -> bool:
    try:
        expected = sign_file(file_path, key)
        return hmac.compare_digest(expected, signature)
    except FileNotFoundError:
        return False


def sign_manifest(data: Dict[str, Any], key: Optional[str] = None) -> Dict[str, Any]:
    result = dict(data)
    sig = sign_data(data, key)
    result["_signature"] = sig
    return result


def verify_manifest(data: Dict[str, Any], key: Optional[str] = None) -> bool:
    if "_signature" not in data:
        return False
    expected = data.pop("_signature")
    return verify_signature(data, expected, key)
