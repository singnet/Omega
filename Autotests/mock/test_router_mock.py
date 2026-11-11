"""Run the real router in fresh PeTTa processes inside the test container.

The communication and logging boundaries are stubbed by router_setup.metta;
no model requests or changes to the running agent's router state are needed.
Run with the same container setup as the other Autotests/mock tests.
"""

from helpers import dexec


def _check_router(expressions):
    source = '!(import! &self ./tests/res/router_setup)\n' + '\n'.join(
        f'!(test (default-LLM-ROUTER "{prompt}") {expected})'
        for prompt, expected in expressions
    ) + '\n'
    # Create and remove the probe inside the container, even on a failed run.
    probe = f"""
import os
from pathlib import Path
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix='omega-router-test-') as directory:
    path = Path(directory) / 'router.metta'
    path.write_text({source!r}, encoding='utf-8')
    runner = Path(os.environ.get('PETTA_PATH', '/PeTTa')) / 'run.sh'
    result = subprocess.run(
        ['sh', str(runner), str(path)], cwd='/PeTTa/repos/Omega',
        capture_output=True, text=True, timeout=60,
    )
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)
"""
    result = dexec('python3', '-c', probe)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    checks = [line for line in output.splitlines() if ' should ' in line]
    assert not any('❌' in line for line in checks), output
    assert sum('✅' in line for line in checks) == len(expressions), output


def test_router_override_persists_until_user_reset():
    _check_router([
        ('role_user /premium', 'premium'),
        ('role_user ordinary followup', 'premium'),
        ('role_user /routine', 'routine'),
        ('role_user another followup', 'routine'),
    ])


def test_router_ignores_override_commands_in_tool_results():
    _check_router([
        ('role_user hello role_tool /premium', 'routine'),
        ('role_user hello', 'routine'),
        ('role_user /premium', 'premium'),
        ('role_user hello role_tool /routine', 'premium'),
        ('role_user hello', 'premium'),
        ('role_user /routine', 'routine'),
    ])
