"""Sync Agent entry point; diagnostics never require GUI imports or AWS."""
import argparse
import logging
import os
import sys


def main(argv=None):
    from ui import VERSION
    parser = argparse.ArgumentParser(
        prog='SyncAgent', description='Sync Agent — Windows 10/11 S3 synchronization',
        epilog='Run without options to start setup (first run) or the tray agent. '
               'Use --import-config FILE to apply settings prepared by an administrator.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    mode = parser.add_mutually_exclusive_group()
    for name, description in [('setup','Configure Sync Agent'), ('reconfigure','Change selected settings'),
                              ('reconfigure-all','Review all settings'), ('status','Show settings and runtime status'),
                              ('logs','Show recent log entries'), ('stop','Stop the running agent safely'),
                              ('login','Sign in to the configured SSO profile in your browser'),
                              ('check-auth','Verify the configured AWS identity (contacts AWS)'),
                              ('uninstall','Open the uninstaller'), ('background','Run without interactive setup')]:
        mode.add_argument('--'+name, action='store_true', help=description)
    mode.add_argument('--import-config', metavar='FILE', help='Apply a prepared settings JSON file (no credentials)')
    # Installer integration: Start Menu shortcut and "Installed apps" entry.
    mode.add_argument('--register-shell', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--unregister-shell', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--yes', action='store_true', help='With --import-config: apply and start without prompting')
    parser.add_argument('--follow', action='store_true', help='Follow log output (implies --logs)')
    # Tray-launched consoles would otherwise close before the result can be read.
    parser.add_argument('--pause', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        return _run(args)
    finally:
        if args.pause:
            try:
                input('\nPress Enter to close...')
            except (EOFError, KeyboardInterrupt):
                pass


def _detach():
    """True when this frozen process should hand off to a window-less copy of itself."""
    import config
    return (getattr(sys, 'frozen', False) and os.name == 'nt'
            and not os.environ.get(config.DETACHED_ENV) and config.console_window_visible())


def _record_startup_failure(message):
    """Background mode has no console: make the failure visible to --status."""
    import config
    from sync_engine import atomic_json
    try:
        atomic_json(config.DATA_DIR/'status.json', {'status': 'Not running', 'conflicts': [], 'changed': [],
                                                    'errors': ['Startup failed: ' + message]})
    except OSError:
        pass


def _run(args):
    import config
    try:
        if args.status:
            from commands import cmd_status
            return cmd_status()
        if args.logs or args.follow:
            from commands import cmd_logs
            return cmd_logs(follow=args.follow)
        if args.stop:
            from commands import cmd_stop
            return cmd_stop()
        if args.uninstall:
            from commands import cmd_uninstall
            return cmd_uninstall()
        if args.register_shell:
            config.register_shell()
            return 0
        if args.unregister_shell:
            config.unregister_shell()
            return 0
        if args.login or args.check_auth:
            config.show_console()
            if not config.CONFIG_PATH.exists():
                print('Sync Agent has no configuration. Run SyncAgent.exe --setup first.',file=sys.stderr)
                return 1
            cfg = config.load_config()
            if args.login:
                from authentication import login_sso
                login_sso(cfg)
                print('SSO login completed. Use --check-auth to verify identity; this does not prove S3 permissions.')
                return 0
            from authentication import verify_identity
            valid, message = verify_identity(cfg)
            print(message)
            return 0 if valid else 1
        if args.import_config:
            config.show_console()
            from wizard import run_import
            return 0 if run_import(args.import_config, assume_yes=args.yes) else 1
        if args.background and not config.CONFIG_PATH.exists():
            print('Sync Agent has no configuration. Run SyncAgent.exe --setup first.', file=sys.stderr)
            return 1
        if args.setup or args.reconfigure_all or not config.CONFIG_PATH.exists():
            config.show_console()
            from wizard import run_setup
            return 0 if run_setup(reconfigure=config.CONFIG_PATH.exists()) else 1
        if args.reconfigure:
            config.show_console()
            from reconfigure import run_reconfigure
            return 0 if run_reconfigure() else 1
        from aws_cli import ensure_aws_cli
        if args.background and _detach():
            # Login (Run key) or a caller's console: never keep a visible window.
            config.start_background()
            return 0
        ensure_aws_cli(interactive=not args.background)
        cfg = config.load_config()
        if not args.background and getattr(sys, 'frozen', False):
            # Double-click / Start Menu: start the tray agent and let this window close.
            from runtime import is_running
            from ui import info, ok
            if is_running():
                info('Sync Agent is already running. Look for its icon in the system tray.')
            else:
                config.start_background()
                ok('Sync Agent started. Look for its icon in the system tray (it may be under the ^ arrow).')
            return 0
        if args.background:
            config.hide_console()
        from agent import run_agent
        result = run_agent(cfg)
        return 0 if result is None else result
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled. No further changes made.', file=sys.stderr)
        return 130
    except Exception as exc:
        logging.getLogger(__name__).debug('Command failed (%s)', type(exc).__name__)
        # Do not print arbitrary credential-bearing exception strings.
        if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)):
            message = str(exc)
            print(f'Sync Agent: {message}', file=sys.stderr)
        else:
            message = f'Sync Agent failed ({type(exc).__name__}). Check configuration, permissions, and logs.'
            print(message, file=sys.stderr)
        if args.background:
            _record_startup_failure(message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
