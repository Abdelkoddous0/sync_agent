"""Change selected settings without replacing unrelated fields or credentials."""
import config
from helpers import ask, banner, info
from wizard import (edit_identity, edit_credentials, edit_paths, edit_options,
                    ensure_aws_cli, finish_settings, collect_settings)


def run_reconfigure():
    config.show_console()
    banner()
    ensure_aws_cli(interactive=True)
    cfg = dict(config.load_config())
    credentials = None
    while True:
        print(f"\nWorkstation: {cfg.get('workstation_id')}\nFolder: {cfg.get('local_path')}\n"
              f"S3: {cfg.get('s3_bucket')}/{cfg.get('s3_prefix')}")
        print('1 Identity   2 Authentication/region   3 Paths\n'
              '4 Sync options/startup   a All settings   s Save   q Cancel')
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
