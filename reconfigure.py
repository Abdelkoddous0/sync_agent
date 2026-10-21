# ================================================================
#  reconfigure.py — Partial reconfiguration menu
# ================================================================
import sys, subprocess

from rich.rule   import Rule
from rich.panel  import Panel
from rich.table  import Table
from rich        import box

from config  import (CONFIG_PATH, LOG_DIR, load_config,
                     save_config, register_startup,
                     remove_startup, show_console)
from helpers import (con, banner, ok, err, info,
                     ask, confirm, verify_aws)


# ── Current config display ───────────────────────────────────────
def _show_current(cfg: dict):
    con.print()
    con.print(Rule("[cyan]Current Configuration[/]", style="cyan"))
    con.print()
    t = Table(box=box.ROUNDED, border_style="dim",
              show_header=False, padding=(0, 2))
    t.add_column(style="dim",       width=22)
    t.add_column(style="cyan bold", overflow="fold")
    t.add_row("Workstation",   cfg.get("workstation_id", "—"))
    t.add_row("Region",        cfg.get("region", "—"))
    t.add_row("Local Path",    cfg.get("local_path", "—"))
    t.add_row("S3 Target",
              f"s3://{cfg.get('s3_bucket','—')}/"
              f"{cfg.get('s3_prefix','—')}/")
    t.add_row("Debounce",      f"{cfg.get('debounce_secs',5)}s")
    t.add_row("Max Retries",   str(cfg.get("max_retries", 3)))
    t.add_row("Delete to S3",
              "Yes" if cfg.get("delete_on_s3") else "No")
    t.add_row("Sync from S3",
              f"Yes — every {cfg.get('poll_interval',30)}s"
              if cfg.get("sync_from_s3") else "No")
    t.add_row("Notifications",
              "On" if cfg.get("notifications") else "Off")
    t.add_row("Recursive",
              "Yes" if cfg.get("recursive") else "No")
    t.add_row("Excludes",
              ", ".join(cfg.get("exclude_patterns", [])))
    con.print(t)
    con.print()


# ── Individual section handlers ──────────────────────────────────
def _identity(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Workstation Identity[/]", style="cyan"))
    con.print()
    info(f"Current: [cyan]{cfg.get('workstation_id','—')}[/]")
    con.print()
    while True:
        ws_id = ask("New Workstation ID",
                    default=cfg.get("workstation_id", ""))
        if not ws_id:
            err("Required.")
        elif " " in ws_id:
            err("No spaces — use underscores.")
        else:
            cfg["workstation_id"] = ws_id
            cfg["log_file"] = str(LOG_DIR / f"sync_{ws_id}.log")
            ok(f"Updated to: [cyan]{ws_id}[/]")
            break
    return cfg


def _aws(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]AWS Credentials[/]", style="cyan"))
    con.print()
    info(f"Current region: [cyan]{cfg.get('region','—')}[/]")
    info("Leave Access Key blank to keep existing credentials.")
    con.print()

    ak = ask("New Access Key ID (blank = keep current)",
             default="")
    sk = ""
    if ak:
        sk = ask("New Secret Access Key", password=True)

    region = ask(
        "AWS Region",
        default=cfg.get("region", "eu-central-1")
    ) or cfg.get("region", "eu-central-1")

    if ak and sk:
        con.print()
        valid, msg = verify_aws(ak, sk, region)
        if valid:
            ok(f"Valid — Account: [green]{msg}[/]")
            for key, val in [
                ("aws_access_key_id",     ak),
                ("aws_secret_access_key", sk),
                ("region",                region),
            ]:
                subprocess.run(
                    ["aws", "configure", "set", key, val],
                    capture_output=True
                )
            ok("AWS CLI credentials updated.")
        else:
            err(f"Error: {msg}")
            if not confirm("Save anyway?", default=False):
                info("Credentials unchanged.")
                cfg["region"] = region
                return cfg
    else:
        info("Credentials unchanged.")
        subprocess.run(
            ["aws", "configure", "set", "region", region],
            capture_output=True
        )

    cfg["region"] = region
    ok(f"Region: [cyan]{region}[/]")
    return cfg


def _paths(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Sync Paths[/]", style="cyan"))
    con.print()
    info(f"Local: [cyan]{cfg.get('local_path','—')}[/]")
    info(
        f"S3: [cyan]s3://{cfg.get('s3_bucket','—')}/"
        f"{cfg.get('s3_prefix','—')}/[/]"
    )
    con.print()

    from pathlib import Path

    lp = ask("Local folder to watch",
             default=cfg.get("local_path", ""))
    if lp:
        Path(lp).mkdir(parents=True, exist_ok=True)
        cfg["local_path"] = lp
        ok(f"Local: [cyan]{lp}[/]")

    bucket = ask("S3 Bucket name",
                 default=cfg.get("s3_bucket", ""))
    if bucket:
        cfg["s3_bucket"] = bucket

    ws_id  = cfg.get("workstation_id", "ws")
    prefix = ask(
        "S3 Folder prefix",
        default=cfg.get("s3_prefix", f"workstations/{ws_id}")
    ) or cfg.get("s3_prefix", f"workstations/{ws_id}")
    cfg["s3_prefix"] = prefix
    ok(
        f"S3: [cyan]s3://{cfg['s3_bucket']}/"
        f"{cfg['s3_prefix']}/[/]"
    )
    return cfg


def _push_options(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Push Options — Local to S3[/]",
                   style="cyan"))
    con.print()
    cfg["debounce_secs"] = int(
        ask("Debounce delay (seconds)",
            default=str(cfg.get("debounce_secs", 5)))
        or cfg.get("debounce_secs", 5)
    )
    cfg["max_retries"] = int(
        ask("Max retries on failure",
            default=str(cfg.get("max_retries", 3)))
        or cfg.get("max_retries", 3)
    )
    cfg["delete_on_s3"] = confirm(
        "Mirror local deletions to S3?",
        default=cfg.get("delete_on_s3", False)
    )
    cfg["recursive"] = confirm(
        "Watch subfolders recursively?",
        default=cfg.get("recursive", True)
    )
    ok("Push options updated.")
    return cfg


def _pull_options(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Pull Options — S3 to Local[/]",
                   style="cyan"))
    con.print()
    info("Files deleted from S3 are removed locally when enabled.")
    con.print()
    cfg["sync_from_s3"] = confirm(
        "Enable S3 to Local sync?",
        default=cfg.get("sync_from_s3", True)
    )
    if cfg["sync_from_s3"]:
        cfg["poll_interval"] = int(
            ask("How often to check S3 (seconds)",
                default=str(cfg.get("poll_interval", 30)))
            or cfg.get("poll_interval", 30)
        )
        ok(f"S3 checked every [cyan]{cfg['poll_interval']}s[/]")
    else:
        info("S3 to Local pull disabled.")
    return cfg


def _notifications(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Notifications[/]", style="cyan"))
    con.print()
    cfg["notifications"] = confirm(
        "Show Windows toast notifications?",
        default=cfg.get("notifications", True)
    )
    ok(
        f"Notifications: [cyan]"
        f"{'On' if cfg['notifications'] else 'Off'}[/]"
    )
    return cfg


def _excludes(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Exclude Patterns[/]", style="cyan"))
    con.print()
    current = ", ".join(cfg.get("exclude_patterns", []))
    info(f"Current: [dim]{current}[/]")
    con.print()
    exc_raw = ask("Exclude patterns (comma-separated)",
                  default=current)
    cfg["exclude_patterns"] = [
        p.strip() for p in exc_raw.split(",") if p.strip()
    ]
    ok("Exclude patterns updated.")
    return cfg


def _startup(cfg: dict) -> dict:
    con.print()
    con.print(Rule("[cyan]Auto-Start Management[/]",
                   style="cyan"))
    con.print()
    ws_id = cfg.get("workstation_id", "unknown")
    task  = f"HTESyncAgent_{ws_id}"
    res   = subprocess.run(
        f'schtasks /Query /TN "{task}"',
        shell=True, capture_output=True, text=True
    )
    is_registered = res.returncode == 0

    if is_registered:
        ok(f"Startup task registered: [cyan]{task}[/]")
        con.print()
        if confirm("Remove auto-start task?", default=False):
            remove_startup(ws_id)
            ok("Startup task removed.")
        else:
            info("Startup task unchanged.")
    else:
        err(f"No startup task found: {task}")
        con.print()
        if confirm("Register auto-start task?", default=True):
            if register_startup(ws_id, sys.executable):
                ok("Startup task registered.")
            else:
                err("Failed — try as Administrator.")
    return cfg


# ── Main reconfigure menu ────────────────────────────────────────
def run_reconfigure():
    show_console()
    banner()

    if not CONFIG_PATH.exists():
        info("No config found — running full setup.")
        from wizard import run_setup
        run_setup(reconfigure=False)
        return

    cfg     = load_config()
    changed = False

    while True:
        _show_current(cfg)
        con.print(
            Rule("[cyan]What would you like to change?[/]",
                 style="cyan")
        )
        con.print()

        menu = [
            ("1", "Workstation Identity",
             cfg.get("workstation_id", "—")),
            ("2", "AWS Credentials",
             f"Region: {cfg.get('region','—')}"),
            ("3", "Sync Paths",
             cfg.get("local_path", "—")),
            ("4", "Push Options",
             f"Debounce: {cfg.get('debounce_secs',5)}s  "
             f"Retries: {cfg.get('max_retries',3)}  "
             f"Delete: {'Yes' if cfg.get('delete_on_s3') else 'No'}"),
            ("5", "Pull Options",
             f"{'Every ' + str(cfg.get('poll_interval',30)) + 's' if cfg.get('sync_from_s3') else 'Disabled'}"),
            ("6", "Notifications",
             "On" if cfg.get("notifications") else "Off"),
            ("7", "Exclude Patterns",
             ", ".join(cfg.get("exclude_patterns",[])[:2]) + "..."),
            ("8", "Auto-Start",
             "Manage startup task"),
        ]

        for key, name, hint in menu:
            con.print(
                f"  [cyan][{key}][/]  {name}  [dim]{hint}[/]"
            )

        con.print()
        con.print("  [dim]──────────────────────────────[/]")
        con.print(
            "  [yellow][A][/]  Change all settings  "
            "[dim]Full setup wizard[/]"
        )
        con.print("  [green][0][/]  Save and exit")
        con.print()

        choice = ask("Select option").strip().upper()

        if choice == "1":
            cfg = _identity(cfg);       changed = True
        elif choice == "2":
            cfg = _aws(cfg);            changed = True
        elif choice == "3":
            cfg = _paths(cfg);          changed = True
        elif choice == "4":
            cfg = _push_options(cfg);   changed = True
        elif choice == "5":
            cfg = _pull_options(cfg);   changed = True
        elif choice == "6":
            cfg = _notifications(cfg);  changed = True
        elif choice == "7":
            cfg = _excludes(cfg);       changed = True
        elif choice == "8":
            cfg = _startup(cfg)
        elif choice == "A":
            from wizard import run_setup
            run_setup(reconfigure=True)
            return
        elif choice == "0":
            break
        else:
            err("Invalid option.")

    if changed:
        save_config(cfg)
        con.print()
        con.print(Panel(
            "[bold green]Configuration saved![/]\n\n"
            "[dim]Restarting agent with new settings...[/]",
            border_style="green", padding=(0, 4)
        ))
        con.print()
        from agent import launch_agent
        launch_agent(cfg)
    else:
        info("No changes made.")
        con.print()
