"""Safe diagnostic and maintenance commands. No GUI imports at startup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import config


def resource_file(name):
    root = Path(getattr(sys, '_MEIPASS', config.BASE_DIR))
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f'Missing packaged resource: {name}. Rebuild or reinstall Sync Agent.')
    return path


def cmd_status():
    if not config.CONFIG_PATH.exists():
        print(f'Sync Agent is not configured. Expected: {config.CONFIG_PATH}')
        return 0
    cfg = config.load_config()
    print(json.dumps(cfg, indent=2))
    from runtime import is_running
    print('Agent running:' , 'yes' if is_running() else 'no')
    status_file = config.DATA_DIR/'status.json'
    if status_file.exists():
        try:
            print(status_file.read_text(encoding='utf-8'))
        except OSError:
            print('Runtime status is currently unavailable.')
    return 0


def cmd_logs(follow=False):
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
        print(''.join(handle.readlines()[-50:]), end='')
        if follow:
            while True:
                line = handle.readline()
                if line:
                    print(line,end='',flush=True)
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
