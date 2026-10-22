"""Change selected settings without replacing unrelated fields or credentials."""
import config
from helpers import ask, banner, info
from ui import key_values, menu, section
from wizard import (edit_identity, edit_credentials, edit_paths, edit_options,
                    ensure_aws_cli, finish_settings, collect_settings)


def run_reconfigure():
    config.show_console()
    banner()
    ensure_aws_cli(interactive=True)
    cfg = dict(config.load_config())
    credentials = None
    while True:
        section('Reconfigure')
        key_values([('Workstation', cfg.get('workstation_id')), ('Folder', cfg.get('local_path')),
                    ('S3', f"{cfg.get('s3_bucket')}/{cfg.get('s3_prefix')}")])
        menu([('1', 'Identity', 'workstation ID'), ('2', 'Authentication', 'sign-in method and region'),
              ('3', 'Paths', 'local folder, bucket, prefix'), ('4', 'Sync options', 'timers, deletions, startup'),
              ('a', 'All settings', 'walk through every step'), ('s', 'Save', 'review and apply changes'),
              ('q', 'Cancel', 'leave everything unchanged')])
        choice = ask('Selection','q').lower()
        if choice == 'q':
            info('Cancelled. Configuration and credentials unchanged.')
            return False
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
