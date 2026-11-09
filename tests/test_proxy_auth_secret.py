import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_SCRIPT = REPO_ROOT / "proxy" / "nginx.sh"
TEMPLATE = REPO_ROOT / "proxy" / "nginx.conf.template"

pytestmark = pytest.mark.skipif(shutil.which("envsubst") is None, reason="envsubst is not installed")


def _render(tmp_path, **secrets):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nginx = bin_dir / "nginx"
    nginx.write_text("#!/bin/sh\nexit 0\n")
    nginx.chmod(0o755)
    config = tmp_path / "nginx.conf"
    environment = {name: value for name, value in os.environ.items() if not name.endswith("AUTH_SECRET")}
    environment.update(secrets)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["NGINX_TEMPLATE"] = str(TEMPLATE)
    environment["NGINX_CONFIG"] = str(config)
    result = subprocess.run(
        ["sh", str(NGINX_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, config.read_text() if config.exists() else None


def test_old_secret_name_still_enables_auth(tmp_path):
    result, config = _render(tmp_path, OMEGACLAW_AUTH_SECRET="4242")

    assert result.returncode == 0, result.stderr
    assert 'set $auth_secret_value "4242";' in config
    assert '$http_x_auth_token = "4242"' in config
    assert "OMEGACLAW_AUTH_SECRET" in result.stderr


def test_new_secret_name_wins_over_old(tmp_path):
    result, config = _render(tmp_path, OMEGA_AUTH_SECRET="1111", OMEGACLAW_AUTH_SECRET="4242")

    assert result.returncode == 0, result.stderr
    assert 'set $auth_secret_value "1111";' in config
    assert "4242" not in config


def test_without_secret_auth_stays_off(tmp_path):
    result, config = _render(tmp_path)

    assert result.returncode == 0, result.stderr
    assert 'set $auth_secret_value "";' in config
