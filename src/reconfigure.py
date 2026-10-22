"""Change selected settings without replacing unrelated fields or credentials."""
import config
from helpers import ask, banner, confirm, err, info
from ui import key_values, menu, section, warn
from wizard import (edit_identity, edit_credentials, edit_paths, edit_options,
                    ensure_aws_cli, finish_settings, collect_settings)


def run_reconfigure():
    config.show_console()
    banner()
    ensure_aws_cli(interactive=True)
    cfg = dict(config.load_config())
    original = dict(cfg)
    credentials = None
    while True:
        pending = credentials is not None or cfg != original
        section('Reconfigure')
        key_values([('Workstation', cfg.get('workstation_id')), ('Folder', cfg.get('local_path')),
                    ('S3', f"{cfg.get('s3_bucket')}/{cfg.get('s3_prefix')}")])
        if pending:
            warn('Unsaved changes' + (' (new access keys)' if credentials else '') + ': choose s to save them.')
        menu([('1', 'Identity', 'workstation ID'), ('2', 'Authentication', 'sign-in method and region'),
              ('3', 'Paths', 'local folder, bucket, prefix'), ('4', 'Sync options', 'timers, deletions, startup'),
              ('a', 'All settings', 'walk through every step'), ('s', 'Save', 'review and apply changes'),
              ('q', 'Cancel', 'leave everything unchanged')])
        # Pressing Enter after an edit must not silently throw the edit away.
        choice = ask('Selection','s' if pending else 'q').lower()
        if choice == 'q':
            if pending and not confirm('Discard the unsaved changes?', default=False):
                continue
            info('Cancelled. Configuration and credentials unchanged.')
            return False
        try:
            if choice == '1':
                edit_identity(cfg)
            elif choice == '2':
                credentials = edit_credentials(cfg)
            elif choice == '3':
                edit_paths(cfg)
            elif choice == '4':
                edit_options(cfg)
            elif choice == 'a':
                cfg, credentials = collect_settings(cfg)
            elif choice == 's':
                return finish_settings(config.validate_config(cfg),credentials)
        except ValueError as exc:
            err(str(exc))
            info('Nothing was saved. Choose another option, or q to cancel.')
