"""Checked AWS CLI discovery and opt-in Windows current-user bootstrap."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def _candidates() -> list[str]:
    paths: list[str] = []
    # Prefer fixed install locations to an unrelated aws command on PATH.
    for variable, suffix in (
        ('LOCALAPPDATA', 'Programs/Amazon/AWSCLIV2/aws.exe'),
        ('ProgramW6432', 'Amazon/AWSCLIV2/aws.exe'),
        ('ProgramFiles', 'Amazon/AWSCLIV2/aws.exe'),
        ('ProgramFiles(x86)', 'Amazon/AWSCLIV2/aws.exe'),
        ('ProgramFiles', 'Amazon/AWSCLI/bin/aws.exe'),
    ):
        base = os.environ.get(variable)
        if base:
            paths.append(str(Path(base) / suffix))
    found = shutil.which('aws')
    if found:
        paths.append(found)
    return list(dict.fromkeys(paths))


def find_aws_cli() -> str | None:
    """Return an executable whose bounded, checked version probe succeeds."""
    for candidate in _candidates():
        try:
            result = subprocess.run(
                [candidate, '--version'], check=True, capture_output=True,
                text=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if (result.stdout + result.stderr).strip().startswith('aws-cli/'):
                return candidate
        except (OSError, subprocess.SubprocessError, UnicodeError):
            continue
    return None


def ensure_aws_cli(interactive: bool = True) -> str:
    """Find AWS; install only after explicit interactive consent, or raise."""
    existing = find_aws_cli()
    if existing:
        return existing
    if not interactive:
        raise RuntimeError('AWS CLI not found; run SyncAgent.exe --setup interactively to install it.')
    if sys.platform != 'win32':
        raise RuntimeError('AWS CLI not found. Automatic installation is available only on Windows.')
    try:
        accepted = input('Install the official AWS CLI for the current user? [y/N] ').strip().lower()
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeError('AWS CLI installation cancelled.') from exc
    if accepted not in ('y', 'yes'):
        raise RuntimeError('AWS CLI installation cancelled.')
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    script = bundle / 'ensure_aws_cli.ps1'
    if not script.is_file():
        raise RuntimeError(f'AWS CLI installer script missing: {script}')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(script), '-Install'], check=True, timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'AWS CLI installation failed: {exc}') from exc
    installed = find_aws_cli()
    if not installed:
        raise RuntimeError('AWS CLI installer completed, but aws --version still fails.')
    return installed
