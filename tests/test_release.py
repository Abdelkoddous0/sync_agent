"""Release tooling contracts: code signing, acceptance script, PowerShell syntax."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')


def test_build_signs_the_app_before_embedding_it_and_then_the_installer():
    text = (ROOT / 'build.bat').read_text()
    sign_app = text.index('-Path "dist\\SyncAgent\\SyncAgent.exe"')
    build_installer = text.index('--name SyncAgentSetup')
    sign_installer = text.index('-Path "dist\\SyncAgentSetup.exe"')
    assert sign_app < build_installer < sign_installer
    assert 'SYNC_AGENT_SIGN_PFX' in text and 'SYNC_AGENT_SIGN_THUMBPRINT' in text
    # The password is read from the environment by sign.ps1, never put on a command line.
    assert '%SYNC_AGENT_SIGN_PASSWORD%' not in text


def test_signing_script_requires_timestamped_sha256_code_signing():
    text = (ROOT / 'scripts' / 'sign.ps1').read_text(encoding='utf-8')
    for required in ['-HashAlgorithm SHA256', '-TimestampServer', '1.3.6.1.5.5.7.3.3', 'Get-AuthenticodeSignature',
                     'SYNC_AGENT_SIGN_PASSWORD', "'Valid'"]:
        assert required in text


def test_ci_signs_only_with_secrets_and_requires_valid_signatures():
    text = (ROOT / '.github' / 'workflows' / 'windows.yml').read_text()
    assert 'secrets.SIGN_PFX_BASE64' in text and 'secrets.SIGN_PFX_PASSWORD' in text
    assert "if ($signature.Status -ne 'Valid')" in text
    assert 'scripts\\acceptance-test.ps1' in text


def test_acceptance_script_isolates_and_restores_user_state():
    text = (ROOT / 'scripts' / 'acceptance-test.ps1').read_text(encoding='utf-8')
    for required in ["$env:LOCALAPPDATA = Join-Path $root 'Local'", "$env:APPDATA = Join-Path $root 'Roaming'",
                     "AWS_ENDPOINT_URL = 'http://127.0.0.1:9'", "'export', $regPath", "'import', $uninstallBackup",
                     'Set-ItemProperty -LiteralPath $runKey', 'Remove-Item -LiteralPath $root -Recurse']:
        assert required in text


@pytest.mark.parametrize('script', sorted(p.name for p in (ROOT / 'scripts').glob('*.ps1')))
def test_no_psscriptroot_in_parameter_defaults(script):
    # Empty in param() defaults on Windows PowerShell 5.1, which broke the documented command.
    text = (ROOT / 'scripts' / script).read_text(encoding='utf-8')
    start = text.find('param(')
    if start >= 0:
        depth, end = 0, start
        for end in range(start, len(text)):
            depth += {'(': 1, ')': -1}.get(text[end], 0)
            if depth == 0:
                break
        assert '$PSScriptRoot' not in text[start:end]


@pytest.mark.skipif(not POWERSHELL, reason='PowerShell required')
@pytest.mark.parametrize('script', sorted(p.name for p in (ROOT / 'scripts').glob('*.ps1')))
def test_powershell_scripts_parse(script):
    command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT_PATH,[ref]$null,[ref]$e);"
               " if ($e.Count) { $e | ForEach-Object { $_.ToString() }; exit 1 }")
    result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True,
                            timeout=60, env={**os.environ, 'SCRIPT_PATH': str(ROOT / 'scripts' / script)})
    assert result.returncode == 0, result.stdout + result.stderr
