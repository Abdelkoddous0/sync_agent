"""Offline distribution tests. Never download/install AWS or invoke cloud APIs."""
import shutil
import importlib
import subprocess
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class AwsDiscoveryTests(unittest.TestCase):
    def test_discovery_checks_version_and_rejects_broken_candidates(self):
        aws = importlib.import_module('aws_cli')
        with patch.object(aws, '_candidates', return_value=['broken', 'working']), patch.object(
            aws.subprocess, 'run', side_effect=[
                subprocess.CalledProcessError(1, 'broken'),
                subprocess.CompletedProcess([], 0, stdout='aws-cli/2.0 Windows', stderr=''),
            ]
        ) as run:
            self.assertEqual(aws.find_aws_cli(), 'working')
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            self.assertTrue(run.call_args.kwargs['check'])

    def test_noninteractive_missing_never_installs(self):
        aws = importlib.import_module('aws_cli')
        with patch.object(aws, 'find_aws_cli', return_value=None), patch.object(aws.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'AWS CLI.*missing|AWS CLI.*not found'):
                aws.ensure_aws_cli(interactive=False)
            run.assert_not_called()


PWSH = os.environ.get('SYNC_AGENT_TEST_PWSH') or shutil.which('pwsh') or shutil.which('powershell')

@unittest.skipUnless(PWSH, 'PowerShell required for mocked bootstrap execution')
class PowerShellBootstrapTests(unittest.TestCase):
    def bootstrap(self, status='Valid', publisher='Amazon Web Services, Inc.', code=0, reprobe=True):
        # Real bootstrap body; mocks only network, signature and process boundaries.
        source = (ROOT / 'scripts' / 'ensure_aws_cli.ps1').read_text()
        body = source[source.index('\ntry {\n'):]
        with tempfile.TemporaryDirectory(prefix='sync-agent-offline-') as folder:
            marker = Path(folder) / 'msi-invoked'
            harness = Path(folder) / 'bootstrap.ps1'
            escaped = str(marker).replace("'", "''")
            prelude = f'''param([switch]$Install)
$ErrorActionPreference = 'Stop'
$script:probes = 0
function Find-AwsCli {{
    $script:probes++
    if ($script:probes -gt 1 -and ${str(reprobe).lower()}) {{ return 'C:\\fake\\aws.exe' }}
    return $null
}}
function Invoke-WebRequest {{ param($Uri, $OutFile, $MaximumRedirection, $TimeoutSec, [switch]$UseBasicParsing)
    if ($Uri -ne 'https://awscli.amazonaws.com/AWSCLIV2-User.msi') {{ throw 'Unexpected URL' }}
    Set-Content -LiteralPath $OutFile -Value 'offline fake MSI, never executed'
}}
function Get-AuthenticodeSignature {{ param($LiteralPath)
    return [pscustomobject]@{{ Status='{status}'; SignerCertificate=[pscustomobject]@{{Subject='CN=Amazon, O="{publisher}", C=US'}} }}
}}
function Start-Process {{ param($FilePath, $ArgumentList, [switch]$PassThru)
    Set-Content -LiteralPath '{escaped}' -Value 'mock only'
    $p = [pscustomobject]@{{ ExitCode={code}; Handle=1 }}
    $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($Timeout) return $true }}
    return $p
}}
'''
            harness.write_text(prelude + body)
            env = {**os.environ, 'SystemRoot': os.environ.get('SystemRoot',folder)}
            result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness), '-Install'], capture_output=True, text=True, timeout=30,env=env)
            return result, marker.exists()

    def test_signature_invalid_or_wrong_publisher_never_invokes_msi(self):
        for status, publisher in [('NotSigned', 'Amazon Web Services, Inc.'), ('Valid', 'Amazon Evil Inc.'), ('Valid', 'Other Inc.')]:
            with self.subTest(status=status, publisher=publisher):
                result, invoked = self.bootstrap(status=status, publisher=publisher)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(invoked)

    def test_expected_amazon_publishers_are_accepted(self):
        for publisher in ['Amazon.com Services LLC','Amazon Web Services, Inc.','Amazon.com, Inc.']:
            with self.subTest(publisher=publisher):
                result, invoked = self.bootstrap(publisher=publisher)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertTrue(invoked)

    def test_checked_installer_exit_codes(self):
        for code in [0, 3010, 1641, 1602, 1603, 1618]:
            with self.subTest(code=code):
                result, invoked = self.bootstrap(code=code)
                self.assertTrue(invoked, result.stdout + result.stderr)
                self.assertEqual(result.returncode == 0, code in (0, 3010, 1641), result.stdout + result.stderr)

    def test_successful_msi_requires_successful_reprobe(self):
        result, invoked = self.bootstrap(reprobe=False)
        self.assertTrue(invoked)
        self.assertNotEqual(result.returncode, 0)


class DistributionContractTests(unittest.TestCase):
    def test_bootstrap_requires_verified_official_msi(self):
        script = (ROOT / 'scripts' / 'ensure_aws_cli.ps1').read_text()
        for required in ['https://awscli.amazonaws.com/AWSCLIV2-User.msi', 'Get-AuthenticodeSignature', "'Valid'", 'Amazon', '3010', '1641', '--version', 'finally', '-MaximumRedirection 0']:
            self.assertIn(required, script)
        for forbidden in ['Invoke-Expression', 'RunAs', 'AWSCLIV2.msi']:
            self.assertNotIn(forbidden, script)

    def test_install_stages_and_rolls_back_without_admin_or_process_killing(self):
        script = (ROOT / 'scripts' / 'install.ps1').read_text()
        for required in ['Programs\\SyncAgent', 'SyncAgent.exe', '--stop', 'staging', 'backup', 'catch', 'HKCU:', '--background', '--status', 'Read-Host']:
            self.assertIn(required, script)
        for forbidden in ['Stop-Process', 'taskkill', 'HKLM:', 'RunAs']:
            self.assertNotIn(forbidden, script)

    def test_uninstall_preserves_data_and_credentials(self):
        script = (ROOT / 'scripts' / 'uninstall.ps1').read_text()
        self.assertIn('Read-Host', script)
        self.assertIn('--stop', script)
        self.assertIn('cancelled', script)
        self.assertIn('preserved', script)
        self.assertNotIn('Remove-Item $data', script)
        self.assertNotIn('Stop-Process', script)
        self.assertNotIn('taskkill', script)

    def test_one_build_target_and_isolated_dependencies(self):
        script = (ROOT / 'build.bat').read_text()
        for required in ['-m venv', 'requirements.txt', 'main.py', 'SyncAgent', 'ensure_aws_cli.ps1', 'install.ps1', 'uninstall.ps1', 'errorlevel']:
            self.assertIn(required, script)
        self.assertNotIn('hte_sync.py', script)


if __name__ == '__main__':
    unittest.main()
