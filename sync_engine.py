# ================================================================
#  sync_engine.py — Global state, push, pull, S3 poller
# ================================================================
import logging, threading, subprocess, time
from datetime import datetime
from pathlib import Path

from PIL    import Image, ImageDraw
from plyer  import notification

from config import LOG_DIR

# ── Global state ─────────────────────────────────────────────────
cfg          : dict                    = {}
observer                               = None
tray_ref                               = None
last_sync    : float                   = 0.0
sync_status  : str                     = "Idle"
sync_lock    : threading.Lock          = threading.Lock()
poll_running : bool                    = False
poll_thread  : threading.Thread | None = None


# ── Logger ───────────────────────────────────────────────────────
def init_logger(ws_id: str):
    log_path = LOG_DIR / f"sync_{ws_id}.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


# ── Tray icon ────────────────────────────────────────────────────
def make_icon(color=(34, 197, 94)) -> Image.Image:
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=color)
    draw.polygon([(18, 34), (30, 46), (48, 20)], fill="white")
    return img


def update_tray():
    if not tray_ref:
        return
    try:
        if "Failed" in sync_status or "Error" in sync_status:
            col = (220, 53, 69)
        elif any(x in sync_status
                 for x in ["Syncing", "Pushing", "Pulling"]):
            col = (255, 153, 0)
        else:
            col = (34, 197, 94)
        tray_ref.icon  = make_icon(col)
        tray_ref.title = (
            f"HTE Sync [{cfg.get('workstation_id','')}]"
            f" — {sync_status}"
        )
    except Exception:
        pass


def desktop_notify(title: str, msg: str):
    if not cfg.get("notifications", True):
        return
    try:
        notification.notify(
            title=title, message=msg,
            app_name="HTE Sync", timeout=4
        )
    except Exception:
        pass


# ── Commands ─────────────────────────────────────────────────────
def _build_push_cmd() -> list[str]:
    cmd = [
        "aws", "s3", "sync",
        cfg["local_path"],
        f"s3://{cfg['s3_bucket']}/{cfg['s3_prefix']}/"
    ]
    if cfg.get("delete_on_s3"):
        cmd.append("--delete")
    for pat in cfg.get("exclude_patterns", []):
        cmd += ["--exclude", pat]
    return cmd


def _build_pull_cmd() -> list[str]:
    cmd = [
        "aws", "s3", "sync",
        f"s3://{cfg['s3_bucket']}/{cfg['s3_prefix']}/",
        cfg["local_path"],
        "--delete"
    ]
    for pat in cfg.get("exclude_patterns", []):
        cmd += ["--exclude", pat]
    return cmd


# ── Push (Local → S3) ────────────────────────────────────────────
def sync_to_s3(reason: str = "auto"):
    global last_sync, sync_status

    with sync_lock:
        now = time.time()
        if now - last_sync < cfg.get("debounce_secs", 5):
            return
        last_sync = now

    sync_status = "Pushing to S3..."
    update_tray()

    ws    = cfg["workstation_id"]
    cmd   = _build_push_cmd()
    max_r = cfg.get("max_retries", 3)
    no_retry = (
        "invalidclienttokenid", "signaturedoesnotmatch",
        "nosuchbucket", "accessdenied"
    )

    for attempt in range(1, max_r + 1):
        logging.info(f"[PUSH/{reason}] Attempt {attempt}/{max_r}")
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.returncode == 0:
            ts = datetime.now().strftime("%H:%M:%S")
            sync_status = f"OK  {ts}"
            logging.info("Push completed.")
            desktop_notify("HTE Sync — Pushed",
                           f"[{ws}] Local to S3 complete")
            update_tray()
            return

        err = res.stderr.lower()
        logging.error(f"Push failed {attempt}: {res.stderr}")

        if any(k in err for k in no_retry):
            sync_status = "Auth/Config Error"
            desktop_notify("HTE Sync Error",
                           f"[{ws}] Auth error — reconfigure")
            update_tray()
            return

        if attempt < max_r:
            time.sleep(30)

    sync_status = "Push Failed"
    desktop_notify("HTE Sync Failed",
                   f"[{ws}] Push failed after {max_r} attempts")
    update_tray()


# ── Pull (S3 → Local) ────────────────────────────────────────────
def sync_from_s3(reason: str = "poll"):
    global sync_status

    ws  = cfg["workstation_id"]
    cmd = _build_pull_cmd()

    if reason != "poll":
        sync_status = "Pulling from S3..."
        update_tray()

    logging.info(f"[PULL/{reason}] S3 to local starting")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        output = result.stdout.strip()
        if output:
            logging.info(f"S3 to Local changes:\n{output}")
            deleted = [
                l for l in output.splitlines()
                if "delete:" in l.lower()
            ]
            if deleted and reason != "poll":
                desktop_notify(
                    "HTE Sync — Pulled",
                    f"[{ws}] {len(deleted)} file(s) removed"
                )
        else:
            logging.info("S3 to Local: no changes")

        if reason != "poll":
            ts = datetime.now().strftime("%H:%M:%S")
            sync_status = f"OK  {ts}"
            update_tray()
    else:
        err = result.stderr.lower()
        logging.error(f"S3 to Local failed: {result.stderr}")
        if any(k in err for k in (
            "nosuchbucket", "accessdenied", "invalidclienttokenid"
        )):
            desktop_notify("HTE Sync Error",
                           "S3 pull error — check credentials")
        if reason != "poll":
            sync_status = "Pull Failed"
            update_tray()


# ── S3 Poller ────────────────────────────────────────────────────
def start_s3_poller():
    global poll_running
    interval     = cfg.get("poll_interval", 30)
    poll_running = True
    logging.info(f"S3 poller started — every {interval}s")
    while poll_running:
        time.sleep(interval)
        if not poll_running:
            break
        if cfg.get("sync_from_s3", True):
            threading.Thread(
                target=sync_from_s3,
                args=("poll",), daemon=True
            ).start()
    logging.info("S3 poller stopped.")


def stop_s3_poller():
    global poll_running
    poll_running = False
