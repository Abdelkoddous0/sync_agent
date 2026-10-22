"""Sync Agent entry point; diagnostics never require GUI imports or AWS."""
import argparse
import logging
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog='SyncAgent', description='Sync Agent — Windows 10/11 S3 synchronization')
    mode = parser.add_mutually_exclusive_group()
    for name, description in [('setup','Configure Sync Agent'), ('reconfigure','Change selected settings'),
                              ('reconfigure-all','Review all settings'), ('status','Show settings and runtime status'),
                              ('logs','Show recent log entries'), ('stop','Stop the running agent safely'),
                              ('login','Sign in to the configured SSO profile in your browser'),
                              ('check-auth','Verify the configured AWS identity (contacts AWS)'),
                              ('uninstall','Open the uninstaller'), ('background','Run without interactive setup')]:
        mode.add_argument('--'+name, action='store_true', help=description)
    parser.add_argument('--follow', action='store_true', help='Follow log output (implies --logs)')
    args = parser.parse_args(argv)
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
        ensure_aws_cli(interactive=not args.background)
        cfg = config.load_config()
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
            print(f'Sync Agent: {exc}', file=sys.stderr)
        else:
            print(f'Sync Agent failed ({type(exc).__name__}). Check configuration, permissions, and logs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
