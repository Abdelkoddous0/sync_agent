#!/usr/bin/env python3
# ================================================================
#  HTE SYNC AGENT v3.2 — Bidirectional Sync Edition
#  Fixes:
#    - Bidirectional sync (Local ↔ S3)
#    - S3 deletions now mirror to local folder
#    - Background S3 polling thread
#    - Pull from S3 Now tray button
#    - Console hidden on boot
#    - Live PowerShell log terminal
#    - Reconfigure no longer crashes
#    - All tray items robust
# ================================================================
import os, sys, json, time, logging, threading
import subprocess, getpass, argparse, ctypes
from pathlib import Path
from datetime import datetime

from rich.console  import Console
from rich.panel    import Panel
from rich.prompt   import Prompt, Confirm
from rich.table    import Table
from rich.rule     import Rule
from rich.live     import Live
from rich.spinner  import Spinner
from rich          import box

from watchdog.observers import Observer
from watchdog.events    import FileSystemEventHandler
import pystray
from PIL   import Image, ImageDraw
from plyer import notification

# ────────────────────────────────────────────────────────────────
#  PATHS
# ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable
                   if getattr(sys, "frozen", False)
                   else __file__).parent.resolve()

DATA_DIR    = Path(
    os.environ.get("ProgramData", "C:\\ProgramData")
) / "HTESync"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR     = DATA_DIR / "logs"
VBS_PATH    = DATA_DIR / "launch_agent.vbs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ────────────────────────────────────────────────────────────────
#  CONSOLE HELPERS
# ────────────────────────────────────────────────────────────────
def _hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _show_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 1)
        else:
            ctypes.windll.kernel32.AllocConsole()
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────
#  RICH CONSOLE
# ────────────────────────────────────────────────────────────────
con = Console()

# ════════════════════════════════════════════════════════════════
#  CLI HELPERS
# ════════════════════════════════════════════════════════════════

def _banner():
    con.print()
    con.print(Panel.fit(
        "[bold cyan]HTE Sync Agent[/]  [dim]v3.2[/]\n"
        "[dim]AWS S3 Bidirectional Sync — Replaces SyncTrayzor[/]",
        border_style="cyan",
        padding=(0, 4)
    ))
    con.print()


def _step(n: int, total: int, title: str):
    con.print()
    con.print(Rule(
        f"[bold cyan]Step {n}/{total}[/]  [white]{title}[/]",
        style="cyan"
    ))
    con.print()


def _ok(msg: str):
    con.print(f"  [bold green]✓[/]  {msg}")


def _err(msg: str):
    con.print(f"  [bold red]✗[/]  [red]{msg}[/]")


def _info(msg: str):
    con.print(f"  [dim]ℹ[/]  [dim]{msg}[/]")


def _ask(prompt: str, default: str = "",
         password: bool = False) -> str:
    if password:
        val = getpass.getpass(f"  {prompt}: ")
        return val.strip()
    display = (
        f"  [bold]{prompt}[/]"
        + (f" [dim](default: {default})[/]" if default else "")
    )
    val = Prompt.ask(display, default=default, console=con)
    return val.strip()


def _confirm(prompt: str, default: bool = True) -> bool:
    return Confirm.ask(
        f"  [bold]{prompt}[/]",
        default=default,
        console=con
    )


def _verify_aws(ak: str, sk: str,
                region: str) -> tuple[bool, str]:
    with Live(
        Spinner("dots", text=" [dim]Contacting AWS...[/]"),
        console=con, transient=True
    ):
        try:
            result = subprocess.run(
                ["aws", "sts", "get-caller-identity",
                 "--query", "Account", "--output", "text"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ,
                     "AWS_ACCESS_KEY_ID"    : ak,
                     "AWS_SECRET_ACCESS_KEY": sk,
                     "AWS_DEFAULT_REGION"   : region}
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip()[:200]
        except subprocess.TimeoutExpired:
            return False, "Connection timed out (15s)"
        except FileNotFoundError:
            return False, "AWS CLI not found"
        except Exception as e:
            return False, str(e)


def _register_startup(ws_id: str, exe_path: str) -> bool:
    """Register via VBS — hides CMD window on boot."""
    try:
        vbs = (
            f'Set WShell = CreateObject("WScript.Shell")\n'
            f'WShell.Run """{exe_path}""", 0, False\n'
        )
        VBS_PATH.write_text(vbs, encoding="utf-8")
        task_name = f"HTESyncAgent_{ws_id}"
        cmd = (
            f'schtasks /Create /SC ONLOGON /RL HIGHEST /F '
            f'/TN "{task_name}" '
            f'/TR "wscript.exe \\"{VBS_PATH}\\""'
        )
        result = subprocess.run(
            cmd, shell=True,
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception as e:
        _err(f"Startup registration failed: {e}")
        return False


def _remove_startup(ws_id: str):
    task_name = f"HTESyncAgent_{ws_id}"
    subprocess.run(
        f'schtasks /Delete /TN "{task_name}" /F',
        shell=True, capture_output=True
    )
    VBS_PATH.unlink(missing_ok=True)


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _save_config(data: dict):
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )

# ════════════════════════════════════════════════════════════════
#  CLI SETUP WIZARD
# ════════════════════════════════════════════════════════════════

def run_setup(reconfigure: bool = False):
    _show_console()
    _banner()

    if reconfigure:
        con.print(Panel(
            "[yellow]Reconfiguration mode — "
            "existing settings will be overwritten.[/]",
            border_style="yellow", padding=(0, 2)
        ))
        con.print()

    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = _load_config()
        except Exception:
            pass

    TOTAL = 6

    # ── STEP 1: Workstation ID ───────────────────────────────
    _step(1, TOTAL, "Workstation Identity")
    _info("Unique name for this machine — no spaces allowed.")
    _info("Examples: ws22  ws_test01  hte_lab3")
    con.print()

    while True:
        ws_id = _ask(
            "Workstation ID",
            default=existing.get("workstation_id", "")
        )
        if not ws_id:
            _err("Workstation ID is required.")
        elif " " in ws_id:
            _err("No spaces — use underscores.")
        else:
            _ok(f"ID set to: [cyan]{ws_id}[/]")
            break

    # ── STEP 2: AWS Credentials ──────────────────────────────
    _step(2, TOTAL, "AWS Credentials")
    _info("IAM access keys — stored locally in AWS CLI profile.")
    con.print()

    while True:
        ak = _ask("AWS Access Key ID",
                  default=existing.get("_ak_hint", ""))
        if not ak:
            _err("Access Key ID is required.")
            continue

        sk = _ask("AWS Secret Access Key", password=True)
        if not sk:
            _err("Secret Access Key is required.")
            continue

        region = _ask(
            "AWS Region",
            default=existing.get("region", "eu-central-1")
        )
        if not region:
            region = "eu-central-1"

        con.print()
        ok, msg = _verify_aws(ak, sk, region)
        if ok:
            _ok(f"Valid — Account: [green]{msg}[/]")
            break
        else:
            _err(f"Credential error: {msg}")
            if not _confirm("Try again?", default=True):
                con.print(
                    "\n[yellow]Proceeding without verification.[/]\n"
                )
                break

    # ── STEP 3: Sync Paths ───────────────────────────────────
    _step(3, TOTAL, "Sync Paths")
    _info("Local folder to watch and its S3 destination.")
    con.print()

    default_lp = existing.get(
        "local_path",
        f"C:\\HTE Sync\\{ws_id}\\data"
    )
    while True:
        local_path = _ask("Local folder to watch",
                          default=default_lp)
        if not local_path:
            _err("Local path is required.")
        else:
            Path(local_path).mkdir(parents=True, exist_ok=True)
            _ok(f"Local: [cyan]{local_path}[/]")
            break

    while True:
        bucket = _ask("S3 Bucket name",
                      default=existing.get("s3_bucket", ""))
        if not bucket:
            _err("S3 Bucket name is required.")
        else:
            break

    default_pfx = existing.get(
        "s3_prefix", f"workstations/{ws_id}"
    )
    prefix = (
        _ask("S3 Folder prefix", default=default_pfx)
        or f"workstations/{ws_id}"
    )
    _ok(f"S3 target: [cyan]s3://{bucket}/{prefix}/[/]")

    # ── STEP 4: Options ──────────────────────────────────────
    _step(4, TOTAL, "Sync Options")
    con.print()

    debounce = int(
        _ask("Debounce delay (seconds)",
             default=str(existing.get("debounce_secs", 5)))
        or 5
    )
    max_retries = int(
        _ask("Max retries on failure",
             default=str(existing.get("max_retries", 3)))
        or 3
    )
    delete_on_s3 = _confirm(
        "Mirror local deletions to S3?",
        default=existing.get("delete_on_s3", False)
    )
    sync_from_s3 = _confirm(
        "Enable S3 to Local sync (pull from S3)?",
        default=existing.get("sync_from_s3", True)
    )

    poll_interval = 30
    if sync_from_s3:
        poll_interval = int(
            _ask(
                "How often to check S3 for changes (seconds)",
                default=str(existing.get("poll_interval", 30))
            ) or 30
        )
        _info(
            f"S3 will be checked every {poll_interval}s. "
            "Files deleted from S3 will be removed locally."
        )

    notifications = _confirm(
        "Show Windows notifications?",
        default=existing.get("notifications", True)
    )
    recursive = _confirm(
        "Watch subfolders recursively?",
        default=existing.get("recursive", True)
    )

    default_exc = ", ".join(
        existing.get(
            "exclude_patterns",
            ["*.tmp", "*.part", "~$*",
             "desktop.ini", "Thumbs.db"]
        )
    )
    exc_raw  = _ask("Exclude patterns", default=default_exc)
    excludes = [
        p.strip() for p in exc_raw.split(",") if p.strip()
    ]

    # ── STEP 5: Auto-Start ───────────────────────────────────
    _step(5, TOTAL, "Windows Auto-Start")
    _info("Starts silently on login — no CMD window visible.")
    con.print()

    register_startup = _confirm(
        "Register auto-start on Windows login?",
        default=True
    )

    # ── STEP 6: Save ─────────────────────────────────────────
    _step(6, TOTAL, "Saving Configuration")
    con.print()

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
    _ok("AWS CLI credentials configured.")

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
    _save_config(config)
    _ok(f"Config saved: [dim]{CONFIG_PATH}[/]")

    if register_startup:
        exe = sys.executable
        if _register_startup(ws_id, exe):
            _ok("Startup task registered — starts hidden on login.")
        else:
            _err("Could not register task (try as Administrator).")

    # Summary table
    con.print()
    con.print(Rule("[green]Summary[/]", style="green"))
    con.print()
    t = Table(box=box.ROUNDED, border_style="dim",
              show_header=False, padding=(0, 2))
    t.add_column(style="dim",       width=22)
    t.add_column(style="cyan bold", overflow="fold")
    t.add_row("Workstation",    ws_id)
    t.add_row("Local Path",     local_path)
    t.add_row("S3 Target",
              f"s3://{bucket}/{prefix}/")
    t.add_row("Region",         region)
    t.add_row("Debounce",       f"{debounce}s")
    t.add_row("Max Retries",    str(max_retries))
    t.add_row("Delete on S3",
              "Yes" if delete_on_s3 else "No")
    t.add_row("Sync from S3",
              f"Yes — every {poll_interval}s"
              if sync_from_s3 else "No")
    t.add_row("Notifications",
              "On" if notifications else "Off")
    t.add_row("Auto-Start",
              "Yes" if register_startup else "No")
    t.add_row("Excludes",       ", ".join(excludes))
    con.print(t)
    con.print()
    con.print(Panel(
        "[bold green]Setup complete![/]\n\n"
        "[dim]Starting agent in system tray...[/]",
        border_style="green", padding=(0, 4)
    ))
    con.print()

    launch_agent(config)

# ════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ════════════════════════════════════════════════════════════════
_cfg          : dict             = {}
_observer     : Observer | None  = None
_tray_ref     : pystray.Icon | None = None
_last_sync    : float            = 0.0
_sync_status  : str              = "Idle"
_sync_lock    : threading.Lock   = threading.Lock()
_poll_running : bool             = False
_poll_thread  : threading.Thread | None = None

# ════════════════════════════════════════════════════════════════
#  SYNC ENGINE
# ════════════════════════════════════════════════════════════════

def _init_logger(ws_id: str):
    log_path = LOG_DIR / f"sync_{ws_id}.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def _make_icon(color=(34, 197, 94)) -> Image.Image:
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=color)
    draw.polygon([(18, 34), (30, 46), (48, 20)], fill="white")
    return img


def _update_tray():
    if not _tray_ref:
        return
    try:
        if "Failed" in _sync_status or "Error" in _sync_status:
            col = (220, 53, 69)
        elif "Syncing" in _sync_status or "Pulling" in _sync_status:
            col = (255, 153, 0)
        else:
            col = (34, 197, 94)
        _tray_ref.icon  = _make_icon(col)
        _tray_ref.title = (
            f"HTE Sync [{_cfg.get('workstation_id','')}]"
            f" — {_sync_status}"
        )
    except Exception:
        pass


def _desktop_notify(title: str, msg: str):
    if not _cfg.get("notifications", True):
        return
    try:
        notification.notify(
            title=title, message=msg,
            app_name="HTE Sync", timeout=4
        )
    except Exception:
        pass


# ── Local → S3 ──────────────────────────────────────────────────
def _build_push_cmd() -> list[str]:
    """Build aws s3 sync command for Local → S3."""
    cmd = [
        "aws", "s3", "sync",
        _cfg["local_path"],
        f"s3://{_cfg['s3_bucket']}/{_cfg['s3_prefix']}/"
    ]
    if _cfg.get("delete_on_s3"):
        cmd.append("--delete")
    for pat in _cfg.get("exclude_patterns", []):
        cmd += ["--exclude", pat]
    return cmd


def sync_to_s3(reason: str = "auto"):
    """Push local changes to S3."""
    global _last_sync, _sync_status

    with _sync_lock:
        now = time.time()
        if now - _last_sync < _cfg.get("debounce_secs", 5):
            return
        _last_sync = now

    _sync_status = "Pushing to S3..."
    _update_tray()

    ws    = _cfg["workstation_id"]
    cmd   = _build_push_cmd()
    max_r = _cfg.get("max_retries", 3)
    no_retry = (
        "invalidclienttokenid",
        "signaturedoesnotmatch",
        "nosuchbucket",
        "accessdenied"
    )

    for attempt in range(1, max_r + 1):
        logging.info(
            f"[PUSH/{reason}] Attempt {attempt}/{max_r}"
        )
        res = subprocess.run(
            cmd, capture_output=True, text=True
        )

        if res.returncode == 0:
            ts = datetime.now().strftime("%H:%M:%S")
            _sync_status = f"OK  {ts}"
            logging.info("Push to S3 completed.")
            _desktop_notify(
                "HTE Sync — Pushed",
                f"[{ws}] Local to S3 sync complete"
            )
            _update_tray()
            return

        err = res.stderr.lower()
        logging.error(
            f"Push failed attempt {attempt}: {res.stderr}"
        )

        if any(k in err for k in no_retry):
            _sync_status = "Auth/Config Error"
            _desktop_notify(
                "HTE Sync Error",
                f"[{ws}] Auth error — reconfigure via tray"
            )
            _update_tray()
            return

        if attempt < max_r:
            logging.info("Retrying push in 30s...")
            time.sleep(30)

    _sync_status = "Push Failed"
    _desktop_notify(
        "HTE Sync Failed",
        f"[{ws}] Push failed after {max_r} attempts"
    )
    _update_tray()


# ── S3 → Local ──────────────────────────────────────────────────
def _build_pull_cmd() -> list[str]:
    """Build aws s3 sync command for S3 → Local (with --delete)."""
    cmd = [
        "aws", "s3", "sync",
        f"s3://{_cfg['s3_bucket']}/{_cfg['s3_prefix']}/",
        _cfg["local_path"],
        "--delete"          # removes local files deleted from S3
    ]
    for pat in _cfg.get("exclude_patterns", []):
        cmd += ["--exclude", pat]
    return cmd


def sync_from_s3(reason: str = "poll"):
    """
    Pull changes from S3 to local.
    Deletes local files that no longer exist in S3.
    """
    global _sync_status

    ws  = _cfg["workstation_id"]
    cmd = _build_pull_cmd()

    if reason != "poll":
        _sync_status = "Pulling from S3..."
        _update_tray()

    logging.info(f"[PULL/{reason}] S3 to local sync starting")

    result = subprocess.run(
        cmd, capture_output=True, text=True
    )

    if result.returncode == 0:
        output = result.stdout.strip()
        if output:
            logging.info(f"S3 to Local changes:\n{output}")
            # Count deleted files
            deleted = [
                l for l in output.splitlines()
                if "delete:" in l.lower()
            ]
            if deleted and reason != "poll":
                _desktop_notify(
                    "HTE Sync — Pulled",
                    f"[{ws}] {len(deleted)} file(s) removed locally"
                )
        else:
            logging.info("S3 to Local: no changes")

        if reason != "poll":
            ts = datetime.now().strftime("%H:%M:%S")
            _sync_status = f"OK  {ts}"
            _update_tray()
    else:
        err = result.stderr.lower()
        logging.error(f"S3 to Local failed: {result.stderr}")
        if any(k in err for k in (
            "nosuchbucket", "accessdenied",
            "invalidclienttokenid"
        )):
            _desktop_notify(
                "HTE Sync Error",
                "S3 pull error — check credentials via tray"
            )
        if reason != "poll":
            _sync_status = "Pull Failed"
            _update_tray()


# ── S3 Polling Thread ────────────────────────────────────────────
def _start_s3_poller():
    """Background thread — periodically pulls S3 → Local."""
    global _poll_running

    interval = _cfg.get("poll_interval", 30)
    _poll_running = True
    logging.info(f"S3 poller started — every {interval}s")

    while _poll_running:
        time.sleep(interval)
        if not _poll_running:
            break
        if _cfg.get("sync_from_s3", True):
            threading.Thread(
                target=sync_from_s3,
                args=("poll",),
                daemon=True
            ).start()

    logging.info("S3 poller stopped.")


def _stop_s3_poller():
    global _poll_running
    _poll_running = False

# ════════════════════════════════════════════════════════════════
#  FILE SYSTEM WATCHER  (Local → S3)
# ════════════════════════════════════════════════════════════════
class SyncHandler(FileSystemEventHandler):
    def _ignored(self, path: str) -> bool:
        name = Path(path).name
        return any(
            name.endswith(p.lstrip("*")) or name == p
            for p in _cfg.get("exclude_patterns", [])
        )

    def _trigger(self, event, label: str):
        if (not event.is_directory
                and not self._ignored(event.src_path)):
            logging.info(f"{label}: {event.src_path}")
            threading.Thread(
                target=sync_to_s3,
                args=(label,),
                daemon=True
            ).start()

    def on_created(self, e):  self._trigger(e, "CREATED")
    def on_modified(self, e): self._trigger(e, "MODIFIED")
    def on_deleted(self, e):  self._trigger(e, "DELETED")
    def on_moved(self, e):    self._trigger(e, "MOVED")

# ════════════════════════════════════════════════════════════════
#  TRAY MENU ACTIONS
# ════════════════════════════════════════════════════════════════

def _tray_push_now(icon, _):
    """Force immediate Local → S3 sync."""
    try:
        threading.Thread(
            target=sync_to_s3,
            args=("manual-push",),
            daemon=True
        ).start()
        _desktop_notify(
            "HTE Sync",
            "Pushing local changes to S3..."
        )
    except Exception as e:
        logging.error(f"Tray push_now error: {e}")


def _tray_pull_now(icon, _):
    """Force immediate S3 → Local sync."""
    try:
        threading.Thread(
            target=sync_from_s3,
            args=("manual-pull",),
            daemon=True
        ).start()
        _desktop_notify(
            "HTE Sync",
            "Pulling changes from S3..."
        )
    except Exception as e:
        logging.error(f"Tray pull_now error: {e}")


def _tray_open_folder(icon, _):
    try:
        p = Path(_cfg.get("local_path", str(DATA_DIR)))
        if p.is_dir():
            os.startfile(str(p))
        else:
            _desktop_notify(
                "HTE Sync",
                f"Folder not found: {p}"
            )
    except Exception as e:
        logging.error(f"Tray open_folder error: {e}")


def _tray_open_logs(icon, _):
    """Open a live color-coded PowerShell log terminal."""
    try:
        log = Path(_cfg.get("log_file", str(LOG_DIR)))
        if not log.exists():
            log.parent.mkdir(parents=True, exist_ok=True)
            log.touch()

        ws = _cfg.get("workstation_id", "agent")
        ps_cmd = (
            f"$host.UI.RawUI.WindowTitle = "
            f"'HTE Sync Live Log — {ws}'; "
            f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' "
            f"-ForegroundColor Cyan; "
            f"Write-Host '  HTE Sync Agent  |  {ws}' "
            f"-ForegroundColor White; "
            f"Write-Host '  {log}' "
            f"-ForegroundColor DarkGray; "
            f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' "
            f"-ForegroundColor Cyan; "
            f"Write-Host ''; "
            f"Get-Content '{log}' -Wait -Tail 50 | "
            f"ForEach-Object {{ "
            f"  if ($_ -match 'ERROR') "
            f"    {{ Write-Host $_ -ForegroundColor Red }} "
            f"  elseif ($_ -match 'completed|OK') "
            f"    {{ Write-Host $_ -ForegroundColor Green }} "
            f"  elseif ($_ -match 'WARNING|Retry|PULL') "
            f"    {{ Write-Host $_ -ForegroundColor Yellow }} "
            f"  elseif ($_ -match 'PUSH') "
            f"    {{ Write-Host $_ -ForegroundColor Cyan }} "
            f"  else "
            f"    {{ Write-Host $_ -ForegroundColor Gray }} "
            f"}}"
        )
        subprocess.Popen(
            ["powershell", "-NoExit", "-Command", ps_cmd],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    except Exception as e:
        logging.error(f"Tray open_logs error: {e}")


def _tray_show_status(icon, _):
    try:
        ws       = _cfg.get("workstation_id", "—")
        lp       = _cfg.get("local_path",     "—")
        s3       = (
            f"s3://{_cfg.get('s3_bucket','')}/"
            f"{_cfg.get('s3_prefix','')}/"
        )
        interval = _cfg.get("poll_interval", 30)
        from_s3  = _cfg.get("sync_from_s3", True)
        _desktop_notify(
            f"HTE Sync — {ws}",
            f"Status : {_sync_status}\n"
            f"Local  : {lp}\n"
            f"S3     : {s3}\n"
            f"Pull   : {'every ' + str(interval) + 's' if from_s3 else 'disabled'}"
        )
    except Exception as e:
        logging.error(f"Tray show_status error: {e}")


def _tray_reconfig(icon, _):
    """Stop everything cleanly then relaunch wizard."""
    global _observer
    try:
        _stop_s3_poller()
        if _observer and _observer.is_alive():
            _observer.stop()
            _observer.join(timeout=5)
        _observer = None
        CONFIG_PATH.unlink(missing_ok=True)
        logging.info("Reconfigure triggered — config deleted.")
        subprocess.Popen(
            [sys.executable, "--reconfigure"],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    except Exception as e:
        logging.error(f"Reconfigure error: {e}")
    finally:
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)


def _tray_quit(icon, _):
    try:
        global _observer
        logging.info("Agent stopped by user.")
        _stop_s3_poller()
        if _observer and _observer.is_alive():
            _observer.stop()
        icon.stop()
    except Exception as e:
        logging.error(f"Tray quit error: {e}")
    finally:
        os._exit(0)


def _build_tray_menu() -> pystray.Menu:
    ws       = _cfg.get("workstation_id", "—")
    lp       = _cfg.get("local_path",     "—")
    s3       = (
        f"s3://{_cfg.get('s3_bucket','')}/"
        f"{_cfg.get('s3_prefix','')}/"
    )
    interval = _cfg.get("poll_interval", 30)
    from_s3  = _cfg.get("sync_from_s3", True)

    return pystray.Menu(
        pystray.MenuItem(
            f"Workstation: {ws}", None, enabled=False),
        pystray.MenuItem(
            f"Local: {lp}",       None, enabled=False),
        pystray.MenuItem(
            f"S3: {s3}",          None, enabled=False),
        pystray.MenuItem(
            lambda _: f"Status: {_sync_status}",
            None, enabled=False),
        pystray.MenuItem(
            f"Pull interval: {interval}s"
            if from_s3 else "Pull from S3: disabled",
            None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Push to S3 Now",    _tray_push_now),
        pystray.MenuItem("Pull from S3 Now",  _tray_pull_now),
        pystray.MenuItem("Show Status",       _tray_show_status),
        pystray.MenuItem("Open Local Folder", _tray_open_folder),
        pystray.MenuItem("View Live Logs",    _tray_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Reconfigure",       _tray_reconfig),
        pystray.MenuItem("Quit",              _tray_quit),
    )

# ════════════════════════════════════════════════════════════════
#  LAUNCH FUNCTIONS
# ════════════════════════════════════════════════════════════════

def launch_wizard():
    _show_console()
    run_setup(reconfigure=False)


def launch_agent(config: dict | None = None):
    global _cfg, _observer, _tray_ref, _poll_thread

    _hide_console()

    _cfg = config or _load_config()
    ws   = _cfg["workstation_id"]
    _init_logger(ws)

    logging.info(f"=== HTE Sync Agent v3.2 started [{ws}] ===")
    logging.info(f"Local      : {_cfg['local_path']}")
    logging.info(
        f"S3 target  : s3://{_cfg['s3_bucket']}"
        f"/{_cfg['s3_prefix']}/"
    )
    logging.info(
        f"Sync from S3: {_cfg.get('sync_from_s3', True)} "
        f"every {_cfg.get('poll_interval', 30)}s"
    )

    _desktop_notify(
        "HTE Sync Started",
        f"[{ws}] Watching {_cfg['local_path']}"
    )

    # Start Local → S3 watcher
    _observer = Observer()
    _observer.schedule(
        SyncHandler(),
        path=_cfg["local_path"],
        recursive=_cfg.get("recursive", True)
    )
    _observer.start()

    # Start S3 → Local poller
    if _cfg.get("sync_from_s3", True):
        _poll_thread = threading.Thread(
            target=_start_s3_poller,
            daemon=True
        )
        _poll_thread.start()

    # Initial sync both directions on startup
    threading.Thread(
        target=sync_to_s3,
        args=("startup",),
        daemon=True
    ).start()

    if _cfg.get("sync_from_s3", True):
        threading.Thread(
            target=sync_from_s3,
            args=("startup",),
            daemon=True
        ).start()

    # System tray (blocking — main thread)
    icon = pystray.Icon(
        "HTESync",
        _make_icon(),
        f"HTE Sync [{ws}]",
        menu=_build_tray_menu()
    )
    _tray_ref = icon
    icon.run()

# ════════════════════════════════════════════════════════════════
#  STATUS / LOGS / UNINSTALL
# ════════════════════════════════════════════════════════════════

def cmd_status():
    _show_console()
    _banner()
    if not CONFIG_PATH.exists():
        con.print("[red]No configuration found.[/]")
        return
    cfg = _load_config()
    ws  = cfg["workstation_id"]
    con.print(Rule("[cyan]Configuration[/]", style="cyan"))
    t = Table(box=box.ROUNDED, border_style="dim",
              show_header=False, padding=(0, 2))
    t.add_column(style="dim",  width=22)
    t.add_column(style="cyan", overflow="fold")
    t.add_row("Workstation",   ws)
    t.add_row("Local Path",    cfg["local_path"])
    t.add_row("S3 Target",
              f"s3://{cfg['s3_bucket']}/{cfg['s3_prefix']}/")
    t.add_row("Region",        cfg["region"])
    t.add_row("Debounce",      f"{cfg['debounce_secs']}s")
    t.add_row("Max Retries",   str(cfg["max_retries"]))
    t.add_row("Delete on S3",
              "Yes" if cfg.get("delete_on_s3") else "No")
    t.add_row("Sync from S3",
              f"Yes — every {cfg.get('poll_interval', 30)}s"
              if cfg.get("sync_from_s3") else "No")
    t.add_row("Notifications",
              "On" if cfg["notifications"] else "Off")
    t.add_row("Log File",      cfg["log_file"])
    con.print(t)
    con.print()
    res = subprocess.run(
        f'schtasks /Query /TN "HTESyncAgent_{ws}" /FO LIST',
        shell=True, capture_output=True, text=True
    )
    if res.returncode == 0:
        _ok(f"Startup task registered: HTESyncAgent_{ws}")
    else:
        _err("Startup task NOT registered.")
    con.print()


def cmd_logs():
    _show_console()
    if not CONFIG_PATH.exists():
        con.print("[red]No configuration found.[/]")
        return
    cfg      = _load_config()
    log_path = Path(cfg["log_file"])
    if not log_path.exists():
        con.print(f"[dim]Log not found: {log_path}[/]")
        return
    ws = cfg["workstation_id"]
    ps_cmd = (
        f"$host.UI.RawUI.WindowTitle = "
        f"'HTE Sync Live Log — {ws}'; "
        f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' "
        f"-ForegroundColor Cyan; "
        f"Write-Host '  HTE Sync Agent  |  {ws}' "
        f"-ForegroundColor White; "
        f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' "
        f"-ForegroundColor Cyan; "
        f"Get-Content '{log_path}' -Wait -Tail 50 | "
        f"ForEach-Object {{ "
        f"  if ($_ -match 'ERROR') "
        f"    {{ Write-Host $_ -ForegroundColor Red }} "
        f"  elseif ($_ -match 'completed|OK') "
        f"    {{ Write-Host $_ -ForegroundColor Green }} "
        f"  elseif ($_ -match 'WARNING|Retry|PULL') "
        f"    {{ Write-Host $_ -ForegroundColor Yellow }} "
        f"  elseif ($_ -match 'PUSH') "
        f"    {{ Write-Host $_ -ForegroundColor Cyan }} "
        f"  else "
        f"    {{ Write-Host $_ -ForegroundColor Gray }} "
        f"}}"
    )
    subprocess.Popen(
        ["powershell", "-NoExit", "-Command", ps_cmd],
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )


def cmd_uninstall():
    _show_console()
    _banner()
    if CONFIG_PATH.exists():
        cfg = _load_config()
        ws  = cfg["workstation_id"]
        if _confirm(
            f"Remove startup task HTESyncAgent_{ws}?"
        ):
            _remove_startup(ws)
            _ok("Startup task removed.")
        if _confirm("Delete config and logs?",
                    default=False):
            CONFIG_PATH.unlink(missing_ok=True)
            _ok("Config deleted.")
    else:
        con.print("[dim]Nothing to uninstall.[/]")
    con.print()

# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="HTESync",
        description="HTE Sync Agent v3.2 — AWS S3 bidirectional sync"
    )
    parser.add_argument(
        "--reconfigure", action="store_true",
        help="Re-run setup wizard"
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
        help="Remove startup task and config"
    )

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.logs or args.follow:
        cmd_logs()
    elif args.uninstall:
        cmd_uninstall()
    elif args.reconfigure:
        run_setup(reconfigure=True)
    elif CONFIG_PATH.exists():
        launch_agent()
    else:
        launch_wizard()


if __name__ == "__main__":
    main()
