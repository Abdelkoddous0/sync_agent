"""Interactive setup and staged reconfiguration; saving is always explicit."""
import json
import os
from pathlib import Path
import re
import subprocess

import config
from helpers import ask, ask_int, banner, confirm, err, info, ok, save_credentials, verify_aws


def ensure_aws_cli(**kwargs):
    from aws_cli import ensure_aws_cli as ensure
    return ensure(**kwargs)


def edit_identity(cfg):
    while True:
        value = ask('Workstation ID (letters, digits, underscore, hyphen)', cfg.get('workstation_id',''))
        if re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
            cfg['workstation_id'] = value
            return
        err('Use 1–64 ASCII letters, digits, underscores or hyphens.')


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
    cfg['region'] = ask('AWS region', cfg.get('region','eu-central-1'))
    choices = {'1':'access_keys','2':'sso','3':'roles_anywhere','4':'workload_role','5':'profile'}
    current = cfg.get('auth_method','access_keys')
    default = next((key for key,value in choices.items() if value == current),'1')
    info('1 Access keys (dedicated profile)   2 Browser SSO (configured profile)')
    info('3 Roles Anywhere (configured certificate-helper profile)')
    info('4 AWS workload/default SDK credential chain   5 Other existing AWS profile')
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
        info('Uses the standard SDK credential chain, NOT a guarantee of role-only credentials.')
        info('Environment variables and default profiles can take precedence over workload roles.')
    else:
        if method == 'sso':
            info('First provision a profile using: aws configure sso --profile YOUR_PROFILE')
            info('This step only selects it. Browser sign-in is offered after saving.')
        elif method == 'roles_anywhere':
            info('Your administrator must provision a trusted AWS signing helper and certificate profile.')
            info('The selected credential_process may execute a local program when credentials are requested.')
        else:
            info('Select a trusted preconfigured AWS profile; its credential process may execute local programs.')
        cfg['aws_profile'] = ask('Existing AWS profile name',cfg.get('aws_profile') or config.AWS_PROFILE)
    validate_auth_profile(cfg)
    info('No AWS profile files changed. Identity verification is offered only after saving.')
    return None


def _edit_access_credentials(cfg):
    info('Use the dedicated sync-agent profile. Credentials are not saved until final confirmation.')
    if not confirm('Enter new AWS access credentials?', default=False):
        valid, message = verify_aws(region=cfg['region'])
        info(message)
        if not valid and not confirm('Continue with existing profile without successful verification?',default=False):
            raise ValueError('Credential verification failed. Configure the sync-agent profile and retry.')
        return None
    access = ask('AWS access key ID')
    secret = ask('AWS secret access key', password=True)
    token = ask('Session token (blank for long-lived credentials)', password=True)
    if not access or not secret:
        raise ValueError('Both access key and secret key are required.')
    valid, message = verify_aws(access,secret,cfg['region'],token)
    info(message)
    if not valid and not confirm('Save unverified credentials anyway?',default=False):
        raise ValueError('Credentials were not accepted; no settings saved.')
    return (access,secret,cfg['region'],token)


def edit_paths(cfg):
    cfg['local_path'] = ask('Absolute local sync folder', cfg.get('local_path',str(Path.home()/'Sync Agent Data')))
    cfg['s3_bucket'] = ask('S3 bucket (name only)',cfg.get('s3_bucket',''))
    cfg['s3_prefix'] = ask('S3 prefix',cfg.get('s3_prefix',f"workstations/{cfg.get('workstation_id','workstation')}"))


def edit_options(cfg):
    cfg['debounce_secs'] = ask_int('Debounce seconds',cfg.get('debounce_secs',5),0,3600)
    cfg['max_retries'] = ask_int('Maximum attempts',cfg.get('max_retries',3),1,10)
    cfg['poll_interval'] = ask_int('Remote poll interval seconds',cfg.get('poll_interval',30),5,86400)
    cfg['transfer_timeout'] = ask_int('Transfer socket timeout seconds',cfg.get('transfer_timeout',120),10,3600)
    cfg['sync_from_s3'] = confirm('Download new/changed S3 objects?',cfg.get('sync_from_s3',True))
    cfg['recursive'] = confirm('Include subfolders?',cfg.get('recursive',True))
    info('Deletion propagation is OFF by default. Enable only after backing up and testing.')
    cfg['delete_on_s3'] = confirm('Propagate baseline-confirmed local deletions to S3?',cfg.get('delete_on_s3',False))
    cfg['delete_local'] = confirm('Propagate baseline-confirmed remote deletions locally?',cfg.get('delete_local',False))
    defaults = cfg.get('exclude_patterns',['*.tmp','*.part','~$*','desktop.ini','Thumbs.db'])
    cfg['exclude_patterns'] = [p.strip() for p in ask('Exclude globs, comma-separated',', '.join(defaults)).split(',') if p.strip()]
    cfg['autostart'] = confirm('Start on current-user Windows login?',cfg.get('autostart',False))


def collect_settings(existing=None):
    cfg = dict(existing or {})
    edit_identity(cfg)
    credentials = edit_credentials(cfg)
    edit_paths(cfg)
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
    print(json.dumps(cfg,indent=2))
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
        valid, message = verify_identity(cfg)
        info(message)
        if not valid:
            info('Settings are saved, but the agent was not started. Fix authentication before starting it.')
            return True
    if confirm('Start Sync Agent now?',default=True):
        subprocess.Popen(config.launch_command('--background'),close_fds=True)
        info('Start requested. Use --status and --logs to confirm runtime health.')
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
