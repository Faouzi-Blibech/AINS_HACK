"""Build & cache the agent-runner Docker image."""
from __future__ import annotations

import subprocess
from pathlib import Path

IMAGE_TAG = "cassette/agent-runner:latest"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DOCKERFILE = _REPO_ROOT / "docker" / "agent-runner.Dockerfile"


def image_exists(runner=subprocess.run) -> bool:
    proc = runner(["docker", "image", "inspect", IMAGE_TAG],
                  capture_output=True, text=True)
    return proc.returncode == 0


def ensure_image(runner=subprocess.run) -> str:
    if image_exists(runner=runner):
        return IMAGE_TAG
    runner(
        ["docker", "build", "-t", IMAGE_TAG, "-f", str(_DOCKERFILE), str(_REPO_ROOT)],
        check=True,
    )
    return IMAGE_TAG
