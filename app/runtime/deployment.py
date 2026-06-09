"""Deployment Manager — handles platform deployment modes.

Capable of deploying in Desktop, Server, Factory, or Research Cluster mode.
Generates appropriate configuration and orchestrates service topology.
"""

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.runtime.deployment")


class DeploymentMode(Enum):
    DESKTOP = "desktop"
    SERVER = "server"
    FACTORY = "factory"
    CLUSTER = "cluster"


@dataclass
class DeploymentProfile:
    mode: DeploymentMode
    label: str = ""
    description: str = ""
    services: List[str] = field(default_factory=list)
    workers: int = 1
    require_docker: bool = False
    require_redis: bool = True
    require_openscad: bool = True
    expose_api: bool = True
    expose_dashboard: bool = False
    telemetry_enabled: bool = False
    config_overrides: Dict[str, Any] = field(default_factory=dict)


DESKTOP_PROFILE = DeploymentProfile(
    mode=DeploymentMode.DESKTOP,
    label="Desktop Engineering Workstation",
    description="Single engineer R&D workstation. Docker Compose based.",
    services=["redis", "api", "worker", "director"],
    workers=1,
    require_docker=True,
    require_openscad=True,
    expose_dashboard=False,
    telemetry_enabled=False,
)

SERVER_PROFILE = DeploymentProfile(
    mode=DeploymentMode.SERVER,
    label="Engineering Server",
    description="Company-wide engineering server. Docker Swarm based.",
    services=["redis", "api", "worker", "director", "experiment", "dashboard"],
    workers=4,
    require_docker=True,
    require_redis=True,
    expose_dashboard=True,
    telemetry_enabled=False,
    config_overrides={
        "api.host": "0.0.0.0",
        "experiment.max_concurrent": 8,
    },
)

FACTORY_PROFILE = DeploymentProfile(
    mode=DeploymentMode.FACTORY,
    label="Factory Deployment",
    description="Production floor deployment with live telemetry feedback.",
    services=["redis", "api", "worker", "director", "telemetry", "knowledge"],
    workers=2,
    require_docker=True,
    require_openscad=True,
    telemetry_enabled=True,
    config_overrides={
        "telemetry.poll_interval_seconds": 10.0,
    },
)

CLUSTER_PROFILE = DeploymentProfile(
    mode=DeploymentMode.CLUSTER,
    label="Research Cluster",
    description="Multi-user research cluster with GPU simulation workers.",
    services=["redis", "api", "experiment", "knowledge", "dashboard"],
    workers=8,
    require_docker=True,
    require_redis=True,
    expose_dashboard=True,
    telemetry_enabled=False,
    config_overrides={
        "experiment.max_concurrent": 16,
        "experiment.default_sample_count": 200,
    },
)


class DeploymentManager:
    """Manages platform deployment across different environments."""

    def __init__(self, workspace: str = "."):
        self.workspace = os.path.abspath(workspace)
        self._profile: Optional[DeploymentProfile] = None

    # ------------------------------------------------------------------
    # Profile lookup
    # ------------------------------------------------------------------

    @staticmethod
    def get_profile(mode: DeploymentMode) -> DeploymentProfile:
        profiles = {
            DeploymentMode.DESKTOP: DESKTOP_PROFILE,
            DeploymentMode.SERVER: SERVER_PROFILE,
            DeploymentMode.FACTORY: FACTORY_PROFILE,
            DeploymentMode.CLUSTER: CLUSTER_PROFILE,
        }
        return profiles[mode]

    @staticmethod
    def list_profiles() -> List[Dict[str, Any]]:
        return [
            {
                "mode": p.mode.value,
                "label": p.label,
                "description": p.description,
                "services": p.services,
                "workers": p.workers,
            }
            for p in [DESKTOP_PROFILE, SERVER_PROFILE, FACTORY_PROFILE, CLUSTER_PROFILE]
        ]

    # ------------------------------------------------------------------
    # Install / Deploy
    # ------------------------------------------------------------------

    def install(self, profile: Optional[DeploymentProfile] = None) -> bool:
        p = profile or DESKTOP_PROFILE
        self._profile = p
        logger.info("Installing platform in mode: %s", p.label)

        if not self._check_prerequisites(p):
            return False

        ok = self._run_docker_compose(p)
        if ok:
            logger.info("Installation complete: %s", p.label)
        else:
            logger.error("Installation failed")
        return ok

    def deploy(self, profile: Optional[DeploymentProfile] = None) -> bool:
        p = profile or SERVER_PROFILE
        self._profile = p
        logger.info("Deploying platform in mode: %s", p.label)

        if not self._check_prerequisites(p):
            return False

        ok = self._run_docker_swarm(p)
        if ok:
            logger.info("Deployment complete: %s", p.label)
        else:
            logger.error("Deployment failed")
        return ok

    def factory_mode(self) -> bool:
        return self.install(FACTORY_PROFILE)

    def cluster_mode(self) -> bool:
        return self.deploy(CLUSTER_PROFILE)

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------

    def _check_prerequisites(self, profile: DeploymentProfile) -> bool:
        if profile.require_docker:
            try:
                subprocess.run(
                    ["docker", "--version"],
                    capture_output=True, timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.error("Docker is required but not found")
                return False

        if profile.require_openscad:
            try:
                subprocess.run(
                    ["openscad", "--version"],
                    capture_output=True, timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.warning("OpenSCAD not found — CAD generation disabled")

        return True

    def _run_docker_compose(self, profile: DeploymentProfile) -> bool:
        compose_file = os.path.join(self.workspace, "docker-compose.yml")
        if not os.path.exists(compose_file):
            logger.error("docker-compose.yml not found at %s", compose_file)
            return False

        self._write_config_overrides(profile)
        logger.info("Running: docker compose up -d")
        try:
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=self.workspace,
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info("docker compose up succeeded")
                return True
            logger.error("docker compose up failed: %s", result.stderr)
            return False
        except Exception as exc:
            logger.error("docker compose error: %s", exc)
            return False

    def _run_docker_swarm(self, profile: DeploymentProfile) -> bool:
        try:
            subprocess.run(
                ["docker", "swarm", "init"],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass

        compose_file = os.path.join(self.workspace, "docker-compose.yml")
        if not os.path.exists(compose_file):
            logger.error("docker-compose.yml not found")
            return False

        logger.info("Running: docker stack deploy")
        try:
            result = subprocess.run(
                ["docker", "stack", "deploy", "-c", compose_file, "engineering"],
                cwd=self.workspace,
                capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.error("docker stack deploy error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _write_config_overrides(self, profile: DeploymentProfile) -> None:
        config_dir = os.path.join(self.workspace, "config")
        os.makedirs(config_dir, exist_ok=True)
        override_path = os.path.join(config_dir, "deployment.yaml")
        data = {
            "deployment_mode": profile.mode.value,
            "workers": profile.workers,
            "telemetry": {"enabled": profile.telemetry_enabled},
            **profile.config_overrides,
        }
        try:
            import yaml
            with open(override_path, "w") as f:
                yaml.dump(data, f)
        except Exception:
            with open(override_path.replace(".yaml", ".json"), "w") as f:
                json.dump(data, f)
        logger.info("Wrote deployment config to %s", override_path)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self._profile.mode.value if self._profile else "unknown",
            "workspace": self.workspace,
            "docker_available": self._check_docker(),
        }

    def _check_docker(self) -> bool:
        try:
            subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False
