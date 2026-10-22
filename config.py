"""Validated, per-user configuration for Sync Agent (Windows 10/11)."""
import ctypes
import ipaddress
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

APP_NAME = 'Sync Agent'
APP_ID = 'SyncAgent'
AWS_PROFILE = 'sync-agent'
BASE_DIR = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / APP_ID
CONFIG_PATH = DATA_DIR / 'config.json'
LOG_DIR = DATA_DIR / 'logs'
PF_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Programs' / APP_ID
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def validate_auth_selection(data):
    """Validate only authentication selectors; no files, credentials or network."""
    method = data.get('auth_method', 'access_keys')
    if method not in ('access_keys', 'profile', 'sso', 'roles_anywhere', 'workload_role'):
        raise ValueError('Unsupported authentication method.')
    profile = data.get('aws_profile', None if method == 'workload_role' else AWS_PROFILE)
    if method == 'workload_role':
        if profile is not None:
            raise ValueError('Workload credential-chain mode must not select an AWS profile.')
    elif not isinstance(profile, str) or not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,128}', profile):
        raise ValueError('AWS profile: use 1–128 ASCII letters, digits or _.@+- characters.')
    if method == 'access_keys' and profile != AWS_PROFILE:
        raise ValueError('Access-key mode requires the dedicated sync-agent AWS profile.')
    return method, profile


def validate_config(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Configuration must be a JSON object.')
    allowed = {'workstation_id', 'local_path', 's3_bucket', 's3_prefix', 'region',
               'aws_profile', 'auth_method', 'debounce_secs', 'max_retries', 'poll_interval',
               'transfer_timeout', 'notifications', 'recursive', 'sync_from_s3',
               'delete_on_s3', 'delete_local', 'autostart', 'exclude_patterns'}
    result = {key: value for key, value in data.items() if key in allowed}
    ws = result.get('workstation_id', '')
    if not isinstance(ws, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ws):
        raise ValueError('Workstation ID: use 1–64 ASCII letters, digits, underscores or hyphens.')
    local = result.get('local_path', '')
    if not isinstance(local, str) or not local or '\x00' in local:
        raise ValueError('Choose an absolute local folder.')
    if not Path(local).is_absolute() and not ntpath.isabs(local):
        raise ValueError('Local folder must be an absolute path.')
    if os.name == 'nt' and not ntpath.splitdrive(local)[0]:
        raise ValueError('Local folder must include a drive or UNC share.')
    if Path(local).is_absolute():
        candidate = Path(local).absolute()
        for part in (candidate, *candidate.parents):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('Sync folder must not contain symlinks or reparse points.')
    result['local_path'] = str(Path(local).absolute()) if Path(local).is_absolute() else ntpath.normpath(local)
    if Path(local).is_absolute():
        root = Path(local).resolve()
        for protected in (DATA_DIR.resolve(), BASE_DIR.resolve(), PF_DIR.resolve()):
            if root == protected or root in protected.parents or protected in root.parents:
                raise ValueError('Sync folder must not overlap application or configuration folders.')
    bucket = result.get('s3_bucket', '')
    if not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket) or '..' in bucket or '.-' in bucket or '-.' in bucket:
        raise ValueError('Enter a valid S3 bucket name (not an s3:// URL).')
    try:
        ipaddress.ip_address(bucket)
    except ValueError:
        pass
    else:
        raise ValueError('S3 bucket must not be an IP address.')
    prefix = result.get('s3_prefix', '')
    if not isinstance(prefix, str) or not prefix or prefix != prefix.strip('/') or '\\' in prefix or any(p in ('', '.', '..') for p in prefix.split('/')) or any(ord(c) < 32 for c in prefix):
        raise ValueError('S3 prefix must be nonempty, without leading/trailing slash, empty or dot components.')
    region = result.setdefault('region', 'eu-central-1')
    if not isinstance(region, str) or not re.fullmatch(r'[a-z]{2}(?:-[a-z0-9]+)+-\d+', region):
        raise ValueError('Enter an AWS region such as eu-central-1.')
    result['auth_method'], result['aws_profile'] = validate_auth_selection(result)
    for key, default, low, high in [('debounce_secs',5,0,3600), ('max_retries',3,1,10), ('poll_interval',30,5,86400), ('transfer_timeout',120,10,3600)]:
        value = result.setdefault(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}.')
    for key, default in [('notifications',True), ('recursive',True), ('sync_from_s3',True), ('delete_on_s3',False), ('delete_local',False), ('autostart',False)]:
        if type(result.setdefault(key, default)) is not bool:
            raise ValueError(f'{key} must be true or false.')
    patterns = result.setdefault('exclude_patterns', ['*.tmp','*.part','~$*','desktop.ini','Thumbs.db'])
    if not isinstance(patterns, list) or len(patterns) > 100 or any(not isinstance(p,str) or not p or len(p)>256 or '\x00' in p for p in patterns):
        raise ValueError('Exclude patterns must be a list of at most 100 nonempty patterns.')
    result['log_file'] = str(LOG_DIR / f'sync_{ws}.log')
    return result


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Cannot read configuration at {CONFIG_PATH}: {exc}') from exc
    return validate_config(data)


def save_config(data: dict):
    checked = validate_config(data)
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='config-', suffix='.tmp', dir=DATA_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(checked, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, CONFIG_PATH)
    finally:
        Path(temp).unlink(missing_ok=True)


def launch_command(*args) -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable, *args]
    return [sys.executable, str(BASE_DIR / 'main.py'), *args]


def register_startup(ws_id: str = '', exe_path: str = '') -> bool:
    """Current-user Run entry: no shell, VBS, elevation, or per-ID task."""
    if os.name != 'nt':
        return False
    import winreg
    try:
        command = subprocess.list2cmdline(launch_command('--background'))
        if len(command) > 260:
            return False
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, command)
        return True
    except OSError:
        return False


def remove_startup(ws_id: str = ''):
    if os.name != 'nt':
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_ID)
    except FileNotFoundError:
        pass


def hide_console():
    if os.name == 'nt':
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)


def show_console():
    if os.name == 'nt':
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 1)
