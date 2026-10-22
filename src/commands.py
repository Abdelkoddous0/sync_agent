"""Safe diagnostic and maintenance commands. No GUI imports at startup."""
import json
import os
from pathlib import Path
import subprocess
import time

import config


def resource_file(name):
    path = config.SCRIPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f'Missing packaged resource: {name}. Rebuild or reinstall Sync Agent.')
    return path


def cmd_status():
    from ui import badge, banner, err, info, key_values, settings_table
    banner('Status')
    if not config.CONFIG_PATH.exists():
        info(f'Sync Agent is not configured. Expected: {config.CONFIG_PATH}')
        info('Run SyncAgent.exe --setup to configure it.')
        return 0
    try:
        cfg = config.load_config()
    except ValueError as exc:
        # Report rather than fail: upgrades run --status and must not be blocked by old settings.
        err(f'Configuration needs repair: {exc}')
        info('Run SyncAgent.exe --setup to review and save valid settings.')
        return 0
    from runtime import is_running
    running = is_running()
    rows = [('Agent', badge('RUNNING' if running else 'STOPPED', running)),
            ('Config', str(config.CONFIG_PATH)), ('Log', cfg['log_file'])]
    status_file = config.DATA_DIR/'status.json'
    if status_file.exists():
        try:
            report = json.loads(status_file.read_text(encoding='utf-8'))
            healthy = report.get('status') == 'Idle'
            rows.insert(1, ('Last pass', badge(str(report.get('status', 'unknown')).upper(), healthy)))
            rows.insert(2, ('Changed', str(len(report.get('changed', [])))))
            rows.insert(3, ('Conflicts', str(len(report.get('conflicts', [])))))
            rows.insert(4, ('Errors', str(len(report.get('errors', [])))))
            report_issues = [*report.get('conflicts', []), *report.get('errors', [])]
        except (OSError, ValueError, TypeError, AttributeError):
            report_issues = []
            rows.append(('Last pass', 'Runtime status is currently unavailable.'))
    else:
        report_issues = []
    key_values(rows)
    for issue in report_issues[:20]:
        err(issue)
    if len(report_issues) > 20:
        info(f'… {len(report_issues) - 20} more; see --logs.')
    settings_table(cfg)
    return 0


def cmd_logs(follow=False):
    from ui import info, log_line
    cfg = config.load_config()
    path = Path(cfg['log_file'])
    if not path.is_file():
        print(f'No log yet: {path}')
        return 0
    with path.open(encoding='utf-8', errors='replace') as handle:
        # Read only a bounded tail, not an unbounded multi-year log.
        size = path.stat().st_size
        handle.seek(max(0,size-65536))
        if size > 65536:
            handle.readline()
        for line in handle.readlines()[-50:]:
            log_line(line)
        if follow:
            info('Following log output; press Ctrl+C to stop.')
            while True:
                line = handle.readline()
                if line:
                    log_line(line)
                else:
                    time.sleep(0.25)
    return 0


def cmd_stop(timeout=30):
    from runtime import request_stop
    if not request_stop(timeout=timeout):
        raise RuntimeError('Sync Agent did not stop in time. No configuration or installation was changed.')
    return 0


def cmd_uninstall():
    if os.name != 'nt':
        raise RuntimeError('The installer/uninstaller supports Windows 10/11 only.')
    script = resource_file('uninstall.ps1')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    # Separate process: allow this executable to exit before it is removed.
    subprocess.Popen([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],
                     cwd=str(Path(os.environ.get('TEMP', str(Path.home())))),
                     creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0), close_fds=True)
    return 0
