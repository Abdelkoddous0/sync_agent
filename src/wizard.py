"""Interactive setup and staged reconfiguration; saving is always explicit."""
import json
import os
from pathlib import Path
import re
import subprocess

import config
from helpers import ask, ask_int, banner, confirm, err, info, ok, save_credentials, verify_aws
from ui import menu, section, settings_table, step, warn, working


def ensure_aws_cli(**kwargs):
    from aws_cli import ensure_aws_cli as ensure
    return ensure(**kwargs)


def default_workstation_id():
    """Suggest the computer name, reduced to the allowed workstation ID characters."""
    import socket
    name = os.environ.get('COMPUTERNAME') or socket.gethostname() or 'workstation'
    return re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-')[:64] or 'workstation'


def ask_valid(prompt, default, check):
    """Re-ask until check(value) accepts it, so one typo never discards earlier answers."""
    while True:
        value = ask(prompt, default)
        try:
            return check(value)
        except ValueError as exc:
            err(str(exc))


def edit_identity(cfg):
    while True:
        value = ask('Workstation ID (letters, digits, underscore, hyphen)',
                    cfg.get('workstation_id') or default_workstation_id())
        if re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
            cfg['workstation_id'] = value
            return
        err('Use 1–64 ASCII letters, digits, underscores or hyphens.')


def list_profiles():
    from authentication import list_profiles as profiles
    return profiles()


def validate_auth_profile(cfg):
    from authentication import validate_auth_profile as validate
    return validate(cfg)


def login_sso(cfg):
    from authentication import login_sso as login
    return login(cfg)


def verify_identity(cfg):
    from authentication import verify_identity as verify
    return verify(cfg)


def edit_credentials(cfg):
    cfg['region'] = ask_valid('AWS region', cfg.get('region','eu-central-1'), config.check_region)
    choices = {'1':'access_keys','2':'sso','3':'roles_anywhere','4':'workload_role','5':'profile'}
    current = cfg.get('auth_method','access_keys')
    default = next((key for key,value in choices.items() if value == current),'1')
    menu([('1', 'Access keys', 'dedicated sync-agent profile'),
          ('2', 'Browser SSO', 'existing IAM Identity Center profile'),
          ('3', 'Roles Anywhere', 'existing certificate-helper profile'),
          ('4', 'Workload / default chain', 'standard SDK credential chain'),
          ('5', 'Other AWS profile', 'existing trusted profile')], title='How should Sync Agent sign in to AWS?')
    while True:
        choice = ask('Authentication method',default)
        if choice in choices:
            break
        err('Choose 1, 2, 3, 4 or 5. Presigned URLs cannot provide full synchronization.')
    method = choices[choice]
    cfg['auth_method'] = method
    if method == 'access_keys':
        cfg['aws_profile'] = config.AWS_PROFILE
        return _edit_access_credentials(cfg)
    if method == 'workload_role':
        cfg['aws_profile'] = None
        warn('Uses the standard SDK credential chain, NOT a guarantee of role-only credentials.')
        warn('Environment variables and default profiles can take precedence over workload roles.')
    else:
        if method == 'sso':
            info('First provision a profile using: aws configure sso --profile YOUR_PROFILE')
            info('This step only selects it. Browser sign-in is offered after saving.')
        elif method == 'roles_anywhere':
            info('Your administrator must provision a trusted AWS signing helper and certificate profile.')
            warn('The selected credential_process may execute a local program when credentials are requested.')
        else:
            warn('Select a trusted preconfigured AWS profile; its credential process may execute local programs.')
        profiles = [name for name in list_profiles() if name != config.AWS_PROFILE or method == 'profile']
        if profiles:
            info('Profiles found on this computer: ' + ', '.join(profiles[:15]))
        while True:
            cfg['aws_profile'] = ask('Existing AWS profile name',cfg.get('aws_profile') or config.AWS_PROFILE)
            try:
                validate_auth_profile(cfg)
                break
            except ValueError as exc:
                err(str(exc))
                if not confirm('Enter a different profile name?', default=True):
                    raise
        info('No AWS profile files changed. Identity verification is offered only after saving.')
        return None
    validate_auth_profile(cfg)
    info('No AWS profile files changed. Identity verification is offered only after saving.')
    return None


def _edit_access_credentials(cfg):
    info('Use the dedicated sync-agent profile. Credentials are not saved until final confirmation.')
    # First installation: there is no profile to reuse, so entering keys is the useful default.
    valid = False
    if config.AWS_PROFILE in list_profiles():
        # Check the saved key first: if AWS rejects it, replacing it is the likely intent.
        with working('Checking the saved access key'):
            valid, message = verify_aws(region=cfg['region'])
        (ok if valid else err)(message)
    if not confirm('Enter new AWS access credentials?', default=not valid):
        if not valid and not confirm('Continue with existing profile without successful verification?',default=False):
            raise ValueError('Credential verification failed. Configure the sync-agent profile and retry.')
        return None
    while True:
        access = ask('AWS access key ID')
        secret = ask('AWS secret access key', password=True)
        token = ask('Session token (blank for long-lived credentials)', password=True)
        if not access or not secret:
            err('Both access key and secret key are required.')
            continue
        valid, message = verify_aws(access,secret,cfg['region'],token)
        (ok if valid else err)(message)
        if valid:
            return (access,secret,cfg['region'],token)
        if confirm('Re-enter the credentials?', default=True):
            continue
        if confirm('Save unverified credentials anyway?',default=False):
            return (access,secret,cfg['region'],token)
        raise ValueError('Credentials were not accepted; no settings saved.')


def edit_paths(cfg):
    cfg['local_path'] = ask_valid('Absolute local sync folder (created if missing)',
                                  cfg.get('local_path',str(Path.home()/'Sync Agent Data')),
                                  lambda value: config.check_local_path(value.strip().strip('"')))
    cfg['s3_bucket'] = ask_valid('S3 bucket (name only)',cfg.get('s3_bucket',''),
                                 lambda value: config.check_bucket(value.removeprefix('s3://').strip('/')))
    cfg['s3_prefix'] = ask_valid('S3 prefix',cfg.get('s3_prefix',f"workstations/{cfg.get('workstation_id','workstation')}"),
                                 lambda value: config.check_prefix(value.strip('/')))


def edit_options(cfg):
    cfg['debounce_secs'] = ask_int('Debounce seconds',cfg.get('debounce_secs',5),0,3600)
    cfg['max_retries'] = ask_int('Maximum attempts',cfg.get('max_retries',3),1,10)
    cfg['poll_interval'] = ask_int('Remote poll interval seconds',cfg.get('poll_interval',30),5,86400)
    cfg['transfer_timeout'] = ask_int('Transfer socket timeout seconds',cfg.get('transfer_timeout',120),10,3600)
    cfg['sync_from_s3'] = confirm('Download new/changed S3 objects?',cfg.get('sync_from_s3',True))
    cfg['recursive'] = confirm('Include subfolders?',cfg.get('recursive',True))
    warn('Deletion propagation is OFF by default. Enable only after backing up and testing.')
    cfg['delete_on_s3'] = confirm('Propagate baseline-confirmed local deletions to S3?',cfg.get('delete_on_s3',False))
    cfg['delete_local'] = confirm('Propagate baseline-confirmed remote deletions locally?',cfg.get('delete_local',False))
    defaults = cfg.get('exclude_patterns',['*.tmp','*.part','~$*','desktop.ini','Thumbs.db'])
    cfg['exclude_patterns'] = [p.strip() for p in ask('Exclude globs, comma-separated',', '.join(defaults)).split(',') if p.strip()]
    cfg['autostart'] = confirm('Start on current-user Windows login?',cfg.get('autostart',False))


def collect_settings(existing=None):
    cfg = dict(existing or {})
    step(1, 4, 'Identity', 'Name this computer; it becomes part of the default S3 prefix.')
    edit_identity(cfg)
    step(2, 4, 'AWS sign-in', 'Choose a region and how credentials are obtained.')
    credentials = edit_credentials(cfg)
    step(3, 4, 'Folders', 'Pick the local folder and the S3 bucket/prefix it mirrors.')
    edit_paths(cfg)
    step(4, 4, 'Sync options', 'Press Enter to keep the safe defaults shown in parentheses.')
    edit_options(cfg)
    return config.validate_config(cfg), credentials


def apply_settings(cfg, credentials=None):
    """Stop before modifying settings; roll back credential/config/startup writes on failure."""
    checked = config.validate_config(cfg)
    if checked.get('auth_method','access_keys') != 'access_keys':
        if credentials:
            raise ValueError('Staged access keys cannot be saved with another authentication method.')
        validate_auth_profile(checked)
    from commands import cmd_stop
    from runtime import RuntimeGuard
    cmd_stop()
    guard = RuntimeGuard()
    if not guard.acquire():
        raise RuntimeError('Another Sync Agent process started during maintenance. Retry after stopping it.')
    try:
        return _apply_settings_locked(checked, credentials)
    finally:
        guard.close()


def _apply_settings_locked(checked, credentials):
    paths = [config.CONFIG_PATH]
    if credentials:
        paths.extend([Path(os.environ.get('AWS_CONFIG_FILE',str(Path.home()/'.aws'/'config'))),
                      Path(os.environ.get('AWS_SHARED_CREDENTIALS_FILE',str(Path.home()/'.aws'/'credentials')))])
    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
    old_startup = None
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,config.RUN_KEY) as key:
                old_startup = winreg.QueryValueEx(key,config.APP_ID)
        except FileNotFoundError:
            pass
    try:
        Path(checked['local_path']).mkdir(parents=True,exist_ok=True)
        if credentials:
            save_credentials(*credentials)
        if checked['autostart']:
            if not config.register_startup():
                raise RuntimeError('Could not register current-user startup. No administrator rights are needed.')
        else:
            config.remove_startup()
        config.save_config(checked)
    except Exception:
        from helpers import _atomic_bytes
        for path, original in previous.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_bytes(path,original)
        if os.name == 'nt':
            if old_startup is None:
                config.remove_startup()
            else:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,config.RUN_KEY) as key:
                    winreg.SetValueEx(key,config.APP_ID,0,old_startup[1],old_startup[0])
        raise
    return checked


def finish_settings(cfg, credentials):
    section('Review')
    settings_table(cfg, 'Settings to save')
    if credentials:
        info('New AWS access keys will be written to the sync-agent profile.')
    if not confirm('Save these settings? The current agent will stop.',default=False):
        info('Cancelled. Configuration and credentials unchanged; running agent left alone.')
        return False
    apply_settings(cfg,credentials)
    ok(f'Settings saved to {config.CONFIG_PATH}.')
    method = cfg.get('auth_method','access_keys')
    verify_now = False
    if method == 'sso':
        if confirm('Sign in to the selected SSO profile in your browser now?',default=True):
            login_sso(cfg)
            verify_now = True
        else:
            info('Sign in later with SyncAgent.exe --login. Background mode never opens a browser.')
    elif method != 'access_keys':
        verify_now = confirm('Verify AWS identity now? This may contact AWS and execute a configured credential helper.',default=True)
    if verify_now:
        with working('Checking AWS identity'):
            valid, message = verify_identity(cfg)
        (ok if valid else err)(message)
        if not valid:
            warn('Settings are saved, but the agent was not started. Fix authentication before starting it.')
            return True
    if confirm('Start Sync Agent now?',default=True):
        subprocess.Popen(config.launch_command('--background'), **config.background_popen_kwargs())
        ok('Start requested. Sync Agent runs in the system tray (it may be under the ^ arrow).')
        info('Use --status and --logs to confirm runtime health.')
    return True


def run_import(path, assume_yes=False, start=None):
    """Apply a prepared settings file (deployment); never writes AWS credentials."""
    banner('Import prepared settings')
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Cannot read settings file {path}: {type(exc).__name__}') from None
    if isinstance(data, dict) and not data.get('workstation_id'):
        data['workstation_id'] = default_workstation_id()
    cfg = config.validate_config(data)
    settings_table(cfg, f'Settings from {Path(path).name}')
    if not assume_yes and not confirm('Apply these settings? The current agent will stop.', default=False):
        info('Cancelled. Configuration unchanged; running agent left alone.')
        return False
    ensure_aws_cli(interactive=not assume_yes)
    apply_settings(cfg)
    ok(f'Settings saved to {config.CONFIG_PATH}.')
    if cfg.get('auth_method') == 'sso':
        if not assume_yes and confirm('Sign in to the selected SSO profile in your browser now?', default=True):
            try:
                login_sso(cfg)
                ok('SSO sign-in completed.')
            except RuntimeError as exc:
                warn(str(exc))
        else:
            info('Sign in with SyncAgent.exe --login before the first sync.')
    if start is None:
        start = assume_yes or confirm('Start Sync Agent now?', default=True)
    if start:
        subprocess.Popen(config.launch_command('--background'), **config.background_popen_kwargs())
        ok('Start requested. Sync Agent runs in the system tray.')
    return True


def run_setup(reconfigure=False):
    config.show_console()
    banner()
    ensure_aws_cli(interactive=True)
    existing = {}
    if config.CONFIG_PATH.exists():
        try:
            existing = config.load_config()
        except ValueError:
            if not confirm('Existing configuration is invalid. Replace it after reviewing all fields?',default=False):
                return False
    cfg, credentials = collect_settings(existing)
    return finish_settings(cfg,credentials)
