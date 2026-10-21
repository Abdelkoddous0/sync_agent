# ================================================================
#  wizard.py — Full first-time setup wizard
# ================================================================
import subprocess
from pathlib import Path

from config  import (CONFIG_PATH, LOG_DIR, load_config,
                     save_config, register_startup, show_console)
from helpers import (con, banner, step, ok, err, info,
                     ask, confirm, verify_aws)
from rich.rule  import Rule
from rich.panel import Panel
from rich.table import Table
from rich       import box


def run_setup(reconfigure: bool = False):
    show_console()
    banner()

    if reconfigure:
        con.print(Panel(
            "[yellow]Full reconfiguration — "
            "all settings will be overwritten.[/]",
            border_style="yellow", padding=(0, 2)
        ))
        con.print()

    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = load_config()
        except Exception:
            pass

    TOTAL = 6

    # ── Step 1: Workstation ID ───────────────────────────────
    step(1, TOTAL, "Workstation Identity")
    info("Unique name — no spaces allowed.")
    info("Examples: ws22  ws_test01  hte_lab3")
    con.print()

    while True:
        ws_id = ask("Workstation ID",
                    default=existing.get("workstation_id", ""))
        if not ws_id:
            err("Required.")
        elif " " in ws_id:
            err("No spaces — use underscores.")
        else:
            ok(f"ID: [cyan]{ws_id}[/]")
            break

    # ── Step 2: AWS Credentials ──────────────────────────────
    step(2, TOTAL, "AWS Credentials")
    info("Stored locally in AWS CLI profile.")
    con.print()

    while True:
        ak = ask("AWS Access Key ID",
                 default=existing.get("_ak_hint", ""))
        if not ak:
            err("Required.")
            continue
        sk = ask("AWS Secret Access Key", password=True)
        if not sk:
            err("Required.")
            continue
        region = ask("AWS Region",
                     default=existing.get("region",
                                          "eu-central-1")
                     ) or "eu-central-1"
        con.print()
        valid, msg = verify_aws(ak, sk, region)
        if valid:
            ok(f"Valid — Account: [green]{msg}[/]")
            break
        else:
            err(f"Error: {msg}")
            if not confirm("Try again?", default=True):
                con.print("\n[yellow]Proceeding without verify.[/]\n")
                break

    # ── Step 3: Sync Paths ───────────────────────────────────
    step(3, TOTAL, "Sync Paths")
    con.print()

    default_lp = existing.get(
        "local_path", f"C:\\HTE Sync\\{ws_id}\\data"
    )
    while True:
        local_path = ask("Local folder to watch",
                         default=default_lp)
        if not local_path:
            err("Required.")
        else:
            Path(local_path).mkdir(parents=True, exist_ok=True)
            ok(f"Local: [cyan]{local_path}[/]")
            break

    while True:
        bucket = ask("S3 Bucket name",
                     default=existing.get("s3_bucket", ""))
        if not bucket:
            err("Required.")
        else:
            break

    default_pfx = existing.get(
        "s3_prefix", f"workstations/{ws_id}"
    )
    prefix = (
        ask("S3 Folder prefix", default=default_pfx)
        or f"workstations/{ws_id}"
    )
    ok(f"S3: [cyan]s3://{bucket}/{prefix}/[/]")

    # ── Step 4: Options ──────────────────────────────────────
    step(4, TOTAL, "Sync Options")
    con.print()

    debounce = int(
        ask("Debounce delay (seconds)",
            default=str(existing.get("debounce_secs", 5)))
        or 5
    )
    max_retries = int(
        ask("Max retries on failure",
            default=str(existing.get("max_retries", 3)))
        or 3
    )
    delete_on_s3 = confirm(
        "Mirror local deletions to S3?",
        default=existing.get("delete_on_s3", False)
    )
    sync_from_s3 = confirm(
        "Enable S3 to Local sync?",
        default=existing.get("sync_from_s3", True)
    )
    poll_interval = 30
    if sync_from_s3:
        poll_interval = int(
            ask("How often to check S3 (seconds)",
                default=str(existing.get("poll_interval", 30)))
            or 30
        )
        info(
            f"S3 checked every {poll_interval}s. "
            "Files deleted from S3 removed locally."
        )
    notifications = confirm(
        "Show Windows notifications?",
        default=existing.get("notifications", True)
    )
    recursive = confirm(
        "Watch subfolders recursively?",
        default=existing.get("recursive", True)
    )
    default_exc = ", ".join(
        existing.get("exclude_patterns",
                     ["*.tmp", "*.part", "~$*",
                      "desktop.ini", "Thumbs.db"])
    )
    exc_raw  = ask("Exclude patterns", default=default_exc)
    excludes = [
        p.strip() for p in exc_raw.split(",") if p.strip()
    ]

    # ── Step 5: Auto-Start ───────────────────────────────────
    step(5, TOTAL, "Windows Auto-Start")
    info("Starts silently on login — no CMD window visible.")
    con.print()

    register_on_boot = confirm(
        "Register auto-start on Windows login?",
        default=True
    )

    # ── Step 6: Save ─────────────────────────────────────────
    step(6, TOTAL, "Saving Configuration")
    con.print()

    from rich.live    import Live
    from rich.spinner import Spinner

    with Live(
        Spinner("dots", text=" [dim]Configuring AWS CLI...[/]"),
        console=con, transient=True
    ):
        for key, val in [
            ("aws_access_key_id",     ak),
            ("aws_secret_access_key", sk),
            ("region",                region),
            ("output",                "json"),
        ]:
            subprocess.run(
                ["aws", "configure", "set", key, val],
                capture_output=True
            )
    ok("AWS CLI credentials configured.")

    import sys
    config = {
        "workstation_id"  : ws_id,
        "local_path"      : local_path,
        "s3_bucket"       : bucket,
        "s3_prefix"       : prefix,
        "region"          : region,
        "debounce_secs"   : debounce,
        "max_retries"     : max_retries,
        "delete_on_s3"    : delete_on_s3,
        "sync_from_s3"    : sync_from_s3,
        "poll_interval"   : poll_interval,
        "notifications"   : notifications,
        "recursive"       : recursive,
        "exclude_patterns": excludes,
        "log_file"        : str(LOG_DIR / f"sync_{ws_id}.log"),
    }
    save_config(config)
    ok(f"Config saved: [dim]{CONFIG_PATH}[/]")

    if register_on_boot:
        if register_startup(ws_id, sys.executable):
            ok("Startup task registered.")
        else:
            err("Could not register (try as Administrator).")

    # Summary
    con.print()
    con.print(Rule("[green]Summary[/]", style="green"))
    con.print()
    t = Table(box=box.ROUNDED, border_style="dim",
              show_header=False, padding=(0, 2))
    t.add_column(style="dim",       width=22)
    t.add_column(style="cyan bold", overflow="fold")
    t.add_row("Workstation",   ws_id)
    t.add_row("Local Path",    local_path)
    t.add_row("S3 Target",     f"s3://{bucket}/{prefix}/")
    t.add_row("Region",        region)
    t.add_row("Debounce",      f"{debounce}s")
    t.add_row("Max Retries",   str(max_retries))
    t.add_row("Delete on S3",  "Yes" if delete_on_s3 else "No")
    t.add_row("Sync from S3",
              f"Yes — every {poll_interval}s"
              if sync_from_s3 else "No")
    t.add_row("Notifications", "On" if notifications else "Off")
    t.add_row("Auto-Start",    "Yes" if register_on_boot else "No")
    t.add_row("Excludes",      ", ".join(excludes))
    con.print(t)
    con.print()
    con.print(Panel(
        "[bold green]Setup complete![/]\n\n"
        "[dim]Starting agent in system tray...[/]",
        border_style="green", padding=(0, 4)
    ))
    con.print()

    from agent import launch_agent
    launch_agent(config)
