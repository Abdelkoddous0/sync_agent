"""Plain console setup helpers; credentials never appear in process arguments."""
import configparser
import getpass
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

from config import APP_NAME, AWS_PROFILE


def banner():
    print('\nSync Agent — Windows 10/11 S3 synchronization\n')


def ok(message):
    print(f'OK: {message}')


def err(message):
    print(f'Error: {message}')


def info(message):
    print(message)


def ask(prompt, default='', password=False):
    if password:
        return getpass.getpass(f'{prompt}: ').strip()
    value = input(f'{prompt}' + (f' [{default}]' if default else '') + ': ').strip()
    return value or default


def confirm(prompt, default=True):
    while True:
        value = input(f'{prompt} [{"Y/n" if default else "y/N"}]: ').strip().lower()
        if not value:
            return default
        if value in ('y','yes'):
            return True
        if value in ('n','no'):
            return False
        print('Please enter yes or no.')


def ask_int(prompt, default, low, high):
    while True:
        try:
            value = int(ask(prompt, str(default)))
            if low <= value <= high:
                return value
        except ValueError:
            pass
        err(f'Enter a whole number from {low} to {high}.')


def _atomic_bytes(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.sync-agent-')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def save_credentials(access_key, secret_key, region, session_token=''):
    """Update only the dedicated profile, restoring both originals on failure."""
    if not access_key or not secret_key:
        raise ValueError('Both access key and secret key are required.')
    if any('\n' in value or '\r' in value for value in (access_key,secret_key,session_token,region)):
        raise ValueError('Credential fields cannot contain line breaks.')
    paths = [Path(os.environ.get('AWS_CONFIG_FILE', str(Path.home()/'.aws'/'config'))),
             Path(os.environ.get('AWS_SHARED_CREDENTIALS_FILE', str(Path.home()/'.aws'/'credentials')))]
    if paths[0].resolve() == paths[1].resolve():
        raise ValueError('AWS configuration and credentials files must be separate files.')
    changes = [{'region':region, 'output':'json'},
               {'aws_access_key_id':access_key,'aws_secret_access_key':secret_key}]
    if session_token:
        changes[1]['aws_session_token'] = session_token
    previous = []
    encoded = []
    for index, path in enumerate(paths):
        old = path.read_bytes() if path.exists() else None
        previous.append(old)
        parser = configparser.RawConfigParser()
        if old is not None:
            parser.read_string(old.decode('utf-8'))
        section = f'profile {AWS_PROFILE}' if index == 0 else AWS_PROFILE
        if not parser.has_section(section):
            parser.add_section(section)
        # Explicit key setup replaces providers only in the dedicated profile.
        # Otherwise an old assume-role/SSO/process directive could select a different identity.
        for key in ('aws_access_key_id','aws_secret_access_key','aws_session_token',
                    'aws_security_token','role_arn','source_profile','credential_source',
                    'credential_process','web_identity_token_file','sso_session',
                    'sso_start_url','sso_region','sso_account_id','sso_role_name',
                    'role_session_name','external_id','duration_seconds'):
            parser.remove_option(section,key)
        for key,value in changes[index].items():
            parser.set(section,key,value)
        stream = io.StringIO()
        parser.write(stream)
        encoded.append(stream.getvalue().encode('utf-8'))
    changed = []
    try:
        for index,path in enumerate(paths):
            _atomic_bytes(path, encoded[index])
            changed.append(index)
    except OSError:
        for index in reversed(changed):
            if previous[index] is None:
                paths[index].unlink(missing_ok=True)
            else:
                _atomic_bytes(paths[index], previous[index])
        raise


def verify_aws(ak='', sk='', region='eu-central-1', session_token=''):
    """Check caller identity without writing supplied credentials to disk."""
    from aws_cli import ensure_aws_cli
    try:
        executable = ensure_aws_cli(interactive=False)
        env = dict(os.environ)
        for key in ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_PROFILE','AWS_DEFAULT_PROFILE'):
            env.pop(key,None)
        command = [executable,'sts','get-caller-identity','--output','json','--region',region,'--no-cli-pager']
        if ak and sk:
            env.update(AWS_ACCESS_KEY_ID=ak,AWS_SECRET_ACCESS_KEY=sk)
            if session_token:
                env['AWS_SESSION_TOKEN'] = session_token
        else:
            command += ['--profile',AWS_PROFILE]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            return False, 'AWS verification failed. Check credentials, session token, region, and connectivity.'
        account = json.loads(result.stdout).get('Account','unknown')
        return True, f'AWS account {account}'
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        return False, f'Unable to verify AWS credentials ({type(exc).__name__}).'
