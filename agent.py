# ================================================================
#  agent.py — launch_agent() coordinator
# ================================================================
import threading, logging

from watchdog.observers import Observer
import pystray

import sync_engine
from config  import load_config, hide_console
from watcher import SyncHandler
from tray    import build_menu


def launch_agent(config: dict | None = None):
    """Start the background sync agent silently."""

    hide_console()

    sync_engine.cfg = config or load_config()
    ws = sync_engine.cfg["workstation_id"]
    sync_engine.init_logger(ws)

    logging.info(f"=== HTE Sync Agent v3.3 started [{ws}] ===")
    logging.info(f"Local  : {sync_engine.cfg['local_path']}")
    logging.info(
        f"S3     : s3://{sync_engine.cfg['s3_bucket']}"
        f"/{sync_engine.cfg['s3_prefix']}/"
    )
    logging.info(
        f"Pull   : {sync_engine.cfg.get('sync_from_s3', True)} "
        f"every {sync_engine.cfg.get('poll_interval', 30)}s"
    )

    sync_engine.desktop_notify(
        "HTE Sync Started",
        f"[{ws}] Watching {sync_engine.cfg['local_path']}"
    )

    # Start Local → S3 watcher
    sync_engine.observer = Observer()
    sync_engine.observer.schedule(
        SyncHandler(),
        path=sync_engine.cfg["local_path"],
        recursive=sync_engine.cfg.get("recursive", True)
    )
    sync_engine.observer.start()

    # Start S3 → Local poller
    if sync_engine.cfg.get("sync_from_s3", True):
        sync_engine.poll_thread = threading.Thread(
            target=sync_engine.start_s3_poller,
            daemon=True
        )
        sync_engine.poll_thread.start()

    # Initial sync both directions on startup
    threading.Thread(
        target=sync_engine.sync_to_s3,
        args=("startup",), daemon=True
    ).start()
    if sync_engine.cfg.get("sync_from_s3", True):
        threading.Thread(
            target=sync_engine.sync_from_s3,
            args=("startup",), daemon=True
        ).start()

    # Start tray icon (blocking — main thread)
    icon = pystray.Icon(
        "HTESync",
        sync_engine.make_icon(),
        f"HTE Sync [{ws}]",
        menu=build_menu()
    )
    sync_engine.tray_ref = icon
    icon.run()
