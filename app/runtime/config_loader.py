"""Runtime configuration loader.

Loads platform configuration from YAML files, environment variables,
and sensible defaults.  Follows: env var > config file > default.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.runtime.config")

DEFAULT_CONFIG_PATHS = [
    "config/platform.yaml",
    "config/platform.json",
    "~/.config/engineering-platform/config.yaml",
]

PROFILE_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config"
)

PROFILE_MAP = {
    "dev": ["config/platform.dev.yaml", "config/platform.dev.json"],
    "staging": ["config/platform.staging.yaml", "config/platform.staging.json"],
    "prod": ["config/platform.prod.yaml", "config/platform.prod.json"],
}

DATA_SUBDIRS = ["knowledge", "experiments", "telemetry", "backups", "logs"]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    socket_timeout: float = 5.0

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


@dataclass
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    log_level: str = "info"
    reload: bool = False


@dataclass
class AgentConfig:
    enabled: bool = True
    register_defaults: bool = True
    max_negotiation_rounds: int = 5


@dataclass
class TelemetryConfig:
    enabled: bool = True
    poll_interval_seconds: float = 60.0
    gateway_host: str = ""
    gateway_port: int = 0


@dataclass
class DirectorConfig:
    enabled: bool = True
    max_iterations: int = 3
    worker_count: int = 1


@dataclass
class KnowledgeConfig:
    store_path: str = "outputs/knowledge"
    archive_enabled: bool = True


@dataclass
class ExperimentConfig:
    enabled: bool = True
    max_concurrent: int = 4
    default_sample_count: int = 50


@dataclass
class DashboardConfig:
    enabled: bool = False
    port: int = 3000


@dataclass
class PlatformConfig:
    redis: RedisConfig = field(default_factory=RedisConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    director: DirectorConfig = field(default_factory=DirectorConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    env: str = "development"
    debug: bool = False
    data_dir: str = "outputs"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _try_load_yaml(path: str) -> Optional[Dict[str, Any]]:
    try:
        import yaml
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _try_load_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return None


def _load_file(path: str) -> Optional[Dict[str, Any]]:
    if path.endswith((".yaml", ".yml")):
        return _try_load_yaml(path)
    return _try_load_json(path)


def _apply_env_overrides(config: PlatformConfig) -> None:
    raw = {
        "redis.host": os.environ.get("ENGINEERING_REDIS_HOST"),
        "redis.port": os.environ.get("ENGINEERING_REDIS_PORT"),
        "api.host": os.environ.get("ENGINEERING_API_HOST"),
        "api.port": os.environ.get("ENGINEERING_API_PORT"),
        "env": os.environ.get("ENGINEERING_ENV"),
        "debug": os.environ.get("ENGINEERING_DEBUG"),
        "data_dir": os.environ.get("ENGINEERING_DATA_DIR"),
    }
    for key, val in raw.items():
        if val is None:
            continue
        parts = key.split(".")
        if len(parts) == 2:
            section, attr = parts
            if hasattr(config, section):
                obj = getattr(config, section)
                if hasattr(obj, attr):
                    typed_val = _coerce(type(getattr(obj, attr)), val)
                    setattr(obj, attr, typed_val)
        elif len(parts) == 1 and hasattr(config, key):
            typed_val = _coerce(type(getattr(config, key)), val)
            setattr(config, key, typed_val)


def _coerce(target_type, val: str):
    if target_type == bool:
        return val.lower() in ("1", "true", "yes")
    if target_type == int:
        return int(val)
    if target_type == float:
        return float(val)
    return val


def merge_dict_into_config(config: PlatformConfig, data: Dict[str, Any]) -> None:
    section_map = {
        "redis": "redis", "api": "api", "agents": "agents",
        "telemetry": "telemetry", "director": "director",
        "knowledge": "knowledge", "experiment": "experiment",
        "dashboard": "dashboard",
    }
    for section_key, attr_name in section_map.items():
        section_data = data.get(section_key, {})
        if isinstance(section_data, dict):
            obj = getattr(config, attr_name)
            for k, v in section_data.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
    for scalar_key in ("env", "debug", "data_dir"):
        if scalar_key in data:
            setattr(config, scalar_key, data[scalar_key])


def _apply_profile_overrides(config: PlatformConfig, profile: str) -> None:
    profile_paths = PROFILE_MAP.get(profile)
    if not profile_paths:
        return
    for p in profile_paths:
        data = _load_file(p)
        if data is not None:
            logger.info("Loaded profile '%s' overrides from %s", profile, p)
            merge_dict_into_config(config, data)
            return


def ensure_data_dirs(config: PlatformConfig) -> List[str]:
    base = os.path.abspath(config.data_dir)
    created: List[str] = []
    for sub in DATA_SUBDIRS:
        path = os.path.join(base, sub)
        os.makedirs(path, exist_ok=True)
        created.append(path)
    os.makedirs(os.path.abspath("config"), exist_ok=True)
    logger.info("Ensured data directories under %s", base)
    return created


def get_data_dir_size(config: PlatformConfig) -> Dict[str, int]:
    base = os.path.abspath(config.data_dir)
    sizes: Dict[str, int] = {}
    for sub in DATA_SUBDIRS:
        path = os.path.join(base, sub)
        if not os.path.isdir(path):
            sizes[sub] = 0
            continue
        total = 0
        for root, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    total += os.path.getsize(os.path.join(root, fname))
                except OSError:
                    pass
        sizes[sub] = total
    return sizes


def load_config(
    paths: Optional[List[str]] = None,
    profile: str = "",
) -> PlatformConfig:
    config = PlatformConfig()

    if profile:
        config.env = profile

    search_paths = paths or DEFAULT_CONFIG_PATHS
    for p in search_paths:
        data = _load_file(p)
        if data is not None:
            logger.info("Loaded config from %s", p)
            merge_dict_into_config(config, data)
            break

    if profile:
        _apply_profile_overrides(config, profile)

    _apply_env_overrides(config)
    return config
