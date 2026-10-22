"""Explicit AWS authentication selectors; background sync never opens a browser."""
from config import validate_auth_selection


def session_kwargs(cfg):
    """Select a named profile or the unmodified SDK default credential chain."""
    method, profile = validate_auth_selection(cfg)
    kwargs = {'region_name': cfg.get('region', 'eu-central-1')}
    if method != 'workload_role':
        kwargs['profile_name'] = profile
    return kwargs


def validate_auth_profile(cfg):
    """Inspect merged local AWS files without resolving credentials or running helpers.

    A credential_process is trusted user configuration, not an executable whose
    authenticity can be established by this structural check.
    """
    method, profile = validate_auth_selection(cfg)
    if method == 'workload_role':
        return
    import botocore.session
    try:
        full = botocore.session.Session().full_config
    except Exception:
        raise ValueError('Cannot read AWS profile configuration; repair the shared AWS files.') from None
    selected = full.get('profiles', {}).get(profile)
    if selected is None:
        raise ValueError('Selected AWS profile does not exist. Configure it before setup.')
    static = {'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token', 'aws_security_token'}
    competing = {'role_arn', 'source_profile', 'credential_source', 'web_identity_token_file'}
    if method == 'sso':
        if (static | competing | {'credential_process'}) & selected.keys():
            raise ValueError('SSO profile contains conflicting credential providers; use a dedicated SSO profile.')
        session_name = selected.get('sso_session')
        if 'sso_session' in selected:
            session = full.get('sso_sessions', {}).get(session_name)
            if not session_name or not isinstance(session, dict):
                raise ValueError('SSO profile references a missing sso-session section.')
            for key in ('sso_start_url', 'sso_region'):
                if key in selected and selected[key] != session.get(key):
                    raise ValueError('SSO profile and sso-session settings disagree.')
        else:
            session = selected
        if not all(isinstance(selected.get(key), str) and selected[key].strip()
                   for key in ('sso_account_id', 'sso_role_name')) or not all(
                   isinstance(session.get(key), str) and session[key].strip()
                   for key in ('sso_start_url', 'sso_region')):
            raise ValueError('SSO profile requires account, role, start URL and SSO region.')
    elif method == 'roles_anywhere':
        sso_fields = {key for key in selected if key.startswith('sso_')}
        if (static | competing | sso_fields) & selected.keys():
            raise ValueError('Roles Anywhere profile contains conflicting credential providers.')
        command = selected.get('credential_process')
        if not isinstance(command, str) or not command.strip():
            raise ValueError('Roles Anywhere requires an existing trusted credential_process profile.')


def login_sso(cfg):
    """Explicit interactive sign-in; never called by the sync engine."""
    if cfg.get('auth_method', 'access_keys') != 'sso':
        raise ValueError('Browser login is available only for SSO authentication.')
    validate_auth_profile(cfg)
    from aws_cli import ensure_aws_cli
    import subprocess
    try:
        executable = ensure_aws_cli(interactive=False)
        subprocess.run([executable, 'sso', 'login', '--profile', cfg['aws_profile'],
                        '--no-cli-pager'], check=True, timeout=300)
    except Exception:
        # CLI output belongs to the interactive console; never capture tokens,
        # authorization URLs or raw helper/CLI exceptions into application logs.
        raise RuntimeError('SSO login failed or timed out. Check AWS CLI installation, profile and connectivity, then retry --login.') from None


def verify_identity(cfg):
    """Explicit AWS STS check; may execute the selected trusted credential helper.

    Socket/retry limits apply to STS, not arbitrary third-party credential helper
    processes. Identity success does not establish bucket or object permissions.
    """
    import boto3
    from botocore.config import Config
    try:
        validate_auth_profile(cfg)
        session = boto3.Session(**session_kwargs(cfg))
        client = session.client('sts', config=Config(
            connect_timeout=5, read_timeout=10,
            retries={'total_max_attempts': 1}))
        identity = client.get_caller_identity()
        # Display the selected principal, not arbitrary provider/response text.
        import re
        account = identity.get('Account', '')
        arn = identity.get('Arn', '')
        if (isinstance(account, str) and re.fullmatch(r'[0-9]{12}', account)
                and isinstance(arn, str) and len(arn) <= 2048
                and re.fullmatch(r'arn:aws[a-z0-9-]*:(?:iam|sts)::' + account
                                 + r':[A-Za-z0-9+=,.@_:/-]+', arn)):
            return True, f'AWS identity verified: account {account}, {arn}. S3 permissions not checked.'
        return True, 'AWS identity verified (principal details omitted). This does not prove S3 permissions.'
    except Exception:
        return False, ('AWS identity verification failed. Check the selected profile, '
                       'credentials or SSO session, helper configuration and connectivity. '
                       'For SSO, sign in explicitly with --login.')
