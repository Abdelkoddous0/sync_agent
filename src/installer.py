"""SyncAgentSetup.exe: one-file installer that installs, then configures, Sync Agent.

The packaged SyncAgent bundle travels inside this executable as data ("payload").
Installation is delegated unchanged to the bundled install.ps1, so ownership,
overlap, staging and rollback protections stay in one place. Configuration is
delegated to the installed SyncAgent.exe (--setup or --import-config).
No administrator rights, AWS calls or credential handling happen here.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import config
from ui import banner, confirm, err, info, key_values, ok, section, warn, working

PAYLOAD_FILES = ('SyncAgent.exe', 'install.ps1', 'uninstall.ps1', 'ensure_aws_cli.ps1')
PREPARED_CONFIG = 'SyncAgent.config.json'


def windows():
    return os.name == 'nt'


def payload_dir(source=None):
    if source:
        return Path(source).resolve()
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'payload'
    return Path(__file__).resolve().parents[1] / 'dist' / 'SyncAgent'


def check_payload(path):
    missing = [name for name in PAYLOAD_FILES if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(f'Installer payload incomplete (missing {", ".join(missing)}). Rebuild SyncAgentSetup.exe.')


def installed_exe():
    return config.PF_DIR / 'SyncAgent.exe'


def existing_settings():
    """Return saved settings as plain JSON, or None; never raises for unreadable files."""
    try:
        data = json.loads(config.CONFIG_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def find_prepared_config(explicit=None):
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'Settings file not found: {path}')
        return path
    # Administrators can ship SyncAgent.config.json next to SyncAgentSetup.exe.
    beside = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent / PREPARED_CONFIG
    return beside if beside.is_file() else None


def powershell():
    return str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')


def run_install_script(source, startup):
    command = [powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
               '-File', str(source / 'install.ps1'), '-SourceDir', str(source), '-Yes']
    if not startup:
        command.append('-NoStartup')
    with working('Installing application files'):
        result = subprocess.run(command, capture_output=True, text=True, errors='replace',
                                timeout=600, check=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        for line in (result.stderr or result.stdout).strip().splitlines()[-12:]:
            err(line)
        raise RuntimeError(f'Installation failed (exit {result.returncode}). Previous installation was restored if present.')


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='SyncAgentSetup', description='Install and configure Sync Agent for the current user.')
    parser.add_argument('--yes', action='store_true', help='Do not ask for confirmation (unattended install)')
    parser.add_argument('--config', metavar='FILE', help=f'Prepared settings to apply (default: {PREPARED_CONFIG} beside this installer)')
    parser.add_argument('--no-configure', action='store_true', help='Install only; skip setup')
    parser.add_argument('--no-startup', action='store_true', help='Never register start at Windows login')
    parser.add_argument('--source', metavar='DIR', help=argparse.SUPPRESS)  # Development: use a built dist\SyncAgent.
    return parser.parse_args(argv)


def install(args):
    banner('Installer')
    if not windows():
        raise RuntimeError('SyncAgentSetup supports Windows 10/11 only.')
    source = payload_dir(args.source)
    check_payload(source)
    prepared = find_prepared_config(args.config)
    previous = existing_settings()
    # Startup is owned by the saved "autostart" setting; setup/import set it afterwards.
    startup = not args.no_startup and bool(previous and previous.get('autostart'))
    upgrading = installed_exe().is_file()

    section('Plan')
    key_values([('Action', 'Upgrade existing installation' if upgrading else 'New installation'),
                ('Application', str(config.PF_DIR)),
                ('Settings & logs', f'{config.DATA_DIR} (kept)'),
                ('Configuration', f'import {prepared.name}' if prepared else
                 'keep existing settings' if previous else
                 'skip' if args.no_configure else 'guided setup after install'),
                ('Administrator', 'not required')])
    if not args.yes and not confirm('Install Sync Agent now?', default=True):
        info('Installation cancelled; no changes made.')
        return 2

    run_install_script(source, startup)
    ok(f'Installed {installed_exe()}')
    exe = str(installed_exe())

    if prepared:
        section('Configure')
        command = [exe, '--import-config', str(prepared)] + (['--yes'] if args.yes else [])
        if subprocess.run(command, check=False).returncode:
            warn('Settings were not applied. Run SyncAgent.exe --setup to configure manually.')
            return 1
    elif previous:
        info('Existing settings kept.')
        if args.yes or confirm('Start Sync Agent now?', default=True):
            subprocess.Popen([exe, '--background'], **config.background_popen_kwargs())
            ok('Start requested. Sync Agent runs in the system tray.')
    elif not args.no_configure and not args.yes:
        section('Configure')
        if subprocess.run([exe, '--setup'], check=False).returncode:
            warn('Setup did not finish. Run it again any time with SyncAgent.exe --setup.')
    else:
        info('Configure later with: "' + exe + '" --setup')

    section('Done')
    key_values([('Start Menu', 'Sync Agent (starts the tray agent, or setup if not configured)'),
                ('Status', f'"{exe}" --status'), ('Reconfigure', f'"{exe}" --reconfigure'),
                ('Uninstall', f'Settings > Apps > Installed apps > Sync Agent, or "{exe}" --uninstall')])
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        code = install(args)
    except (KeyboardInterrupt, EOFError):
        err('Cancelled.')
        code = 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        err(str(exc))
        code = 1
    # Keep a double-clicked console window open long enough to read the result.
    if windows() and not args.yes and sys.stdin and sys.stdin.isatty():
        try:
            input('\nPress Enter to close...')
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
