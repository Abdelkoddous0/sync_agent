# ================================================================
#  tray.py — System tray icon, menu and all tray actions
# ================================================================
import os, sys, ctypes, subprocess, logging, threading
from pathlib import Path

import pystray

import sync_engine
from config import DATA_DIR, VBS_PATH


def _push_now(icon, _):
    try:
        threading.Thread(
            target=sync_engine.sync_to_s3,
            args=("manual-push",), daemon=True
        ).start()
        sync_engine.desktop_notify("HTE Sync", "Pushing to S3...")
    except Exception as e:
        logging.error(f"Tray push_now: {e}")


def _pull_now(icon, _):
    try:
        threading.Thread(
            target=sync_engine.sync_from_s3,
            args=("manual-pull",), daemon=True
        ).start()
        sync_engine.desktop_notify("HTE Sync", "Pulling from S3...")
    except Exception as e:
        logging.error(f"Tray pull_now: {e}")


def _open_folder(icon, _):
    try:
        p = Path(sync_engine.cfg.get("local_path", str(DATA_DIR)))
        if p.is_dir():
            os.startfile(str(p))
        else:
            sync_engine.desktop_notify("HTE Sync",
                                       f"Folder not found: {p}")
    except Exception as e:
        logging.error(f"Tray open_folder: {e}")


def _open_logs(icon, _):
    try:
        log = Path(sync_engine.cfg.get(
            "log_file", str(DATA_DIR / "logs")
        ))
        if not log.exists():
            log.parent.mkdir(parents=True, exist_ok=True)
            log.touch()
        ws = sync_engine.cfg.get("workstation_id", "agent")
        ps_cmd = (
            f"$host.UI.RawUI.WindowTitle = "
            f"'HTE Sync Live Log — {ws}'; "
            f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
            f" -ForegroundColor Cyan; "
            f"Write-Host '  HTE Sync Agent  |  {ws}'"
            f" -ForegroundColor White; "
            f"Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
            f" -ForegroundColor Cyan; "
            f"Get-Content '{log}' -Wait -Tail 50 | "
            f"ForEach-Object {{ "
            f"  if ($_ -match 'ERROR')"
            f"    {{ Write-Host $_ -ForegroundColor Red }}"
            f"  elseif ($_ -match 'completed|OK')"
            f"    {{ Write-Host $_ -ForegroundColor Green }}"
            f"  elseif ($_ -match 'WARNING|Retry|PULL')"
            f"    {{ Write-Host $_ -ForegroundColor Yellow }}"
            f"  elseif ($_ -match 'PUSH')"
            f"    {{ Write-Host $_ -ForegroundColor Cyan }}"
            f"  else"
            f"    {{ Write-Host $_ -ForegroundColor Gray }} }}"
        )
        subprocess.Popen(
            ["powershell", "-NoExit", "-Command", ps_cmd],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    except Exception as e:
        logging.error(f"Tray open_logs: {e}")


def _show_status(icon, _):
    try:
        c        = sync_engine.cfg
        ws       = c.get("workstation_id", "—")
        lp       = c.get("local_path", "—")
        s3       = (f"s3://{c.get('s3_bucket','')}/"
                    f"{c.get('s3_prefix','')}/")
        interval = c.get("poll_interval", 30)
        from_s3  = c.get("sync_from_s3", True)
        sync_engine.desktop_notify(
            f"HTE Sync — {ws}",
            f"Status : {sync_engine.sync_status}\n"
            f"Local  : {lp}\n"
            f"S3     : {s3}\n"
            f"Pull   : "
            + (f"every {interval}s" if from_s3 else "disabled")
        )
    except Exception as e:
        logging.error(f"Tray show_status: {e}")


def _reconfig(icon, _):
    try:
        sync_engine.stop_s3_poller()
        if (sync_engine.observer
                and sync_engine.observer.is_alive()):
            sync_engine.observer.stop()
            sync_engine.observer.join(timeout=5)
        sync_engine.observer = None
        logging.info("Reconfigure triggered from tray.")
        subprocess.Popen(
            [sys.executable, "--reconfigure"],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    except Exception as e:
        logging.error(f"Reconfigure: {e}")
    finally:
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)


def _uninstall(icon, _):
    try:
        result = ctypes.windll.user32.MessageBoxW(
            0,
            "This will uninstall HTE Sync Agent.\n\n"
            "A terminal will open to complete.\n\nContinue?",
            "HTE Sync — Uninstall",
            0x04 | 0x30
        )
        if result != 6:
            return
        sync_engine.stop_s3_poller()
        if (sync_engine.observer
                and sync_engine.observer.is_alive()):
            sync_engine.observer.stop()
            sync_engine.observer.join(timeout=5)
        logging.info("Uninstall triggered from tray.")
        subprocess.Popen(
            [sys.executable, "--uninstall"],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    except Exception as e:
        logging.error(f"Tray uninstall: {e}")
    finally:
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)


def _quit(icon, _):
    try:
        logging.info("Agent stopped by user.")
        sync_engine.stop_s3_poller()
        if (sync_engine.observer
                and sync_engine.observer.is_alive()):
            sync_engine.observer.stop()
        icon.stop()
    except Exception as e:
        logging.error(f"Tray quit: {e}")
    finally:
        os._exit(0)


def build_menu() -> pystray.Menu:
    c        = sync_engine.cfg
    ws       = c.get("workstation_id", "—")
    lp       = c.get("local_path",     "—")
    s3       = (f"s3://{c.get('s3_bucket','')}/"
                f"{c.get('s3_prefix','')}/")
    interval = c.get("poll_interval", 30)
    from_s3  = c.get("sync_from_s3", True)

    return pystray.Menu(
        pystray.MenuItem(
            f"Workstation: {ws}", None, enabled=False),
        pystray.MenuItem(
            f"Local: {lp}",       None, enabled=False),
        pystray.MenuItem(
            f"S3: {s3}",          None, enabled=False),
        pystray.MenuItem(
            lambda _: f"Status: {sync_engine.sync_status}",
            None, enabled=False),
        pystray.MenuItem(
            f"Pull interval: {interval}s"
            if from_s3 else "Pull from S3: disabled",
            None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Push to S3 Now",    _push_now),
        pystray.MenuItem("Pull from S3 Now",  _pull_now),
        pystray.MenuItem("Show Status",       _show_status),
        pystray.MenuItem("Open Local Folder", _open_folder),
        pystray.MenuItem("View Live Logs",    _open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Reconfigure",       _reconfig),
        pystray.MenuItem("Uninstall",         _uninstall),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit",              _quit),
    )
