# ================================================================
#  main.py — Entry point and argument parser
# ================================================================
import sys
from config import CONFIG_PATH, show_console


def launch_wizard():
    show_console()
    from wizard import run_setup
    run_setup(reconfigure=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="HTESync",
        description="HTE Sync Agent v3.3 — AWS S3 Bidirectional Sync"
    )
    parser.add_argument(
        "--reconfigure", action="store_true",
        help="Open partial reconfiguration menu"
    )
    parser.add_argument(
        "--reconfigure-all", action="store_true",
        help="Run full setup wizard from scratch"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current configuration"
    )
    parser.add_argument(
        "--logs", action="store_true",
        help="Open live log terminal"
    )
    parser.add_argument(
        "--follow", action="store_true",
        help="Open live log terminal"
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Run full uninstall wizard"
    )

    args = parser.parse_args()

    if args.status:
        from commands import cmd_status
        cmd_status()

    elif args.logs or args.follow:
        from commands import cmd_logs
        cmd_logs()

    elif args.uninstall:
        from commands import cmd_uninstall
        cmd_uninstall()

    elif args.reconfigure:
        from reconfigure import run_reconfigure
        run_reconfigure()

    elif args.reconfigure_all:
        from wizard import run_setup
        run_setup(reconfigure=True)

    elif CONFIG_PATH.exists():
        from agent import launch_agent
        launch_agent()

    else:
        launch_wizard()


if __name__ == "__main__":
    main()
