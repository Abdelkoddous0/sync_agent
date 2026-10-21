# ================================================================
#  watcher.py — FileSystemWatcher handler (Local → S3 trigger)
# ================================================================
import logging, threading
from pathlib import Path
from watchdog.events import FileSystemEventHandler

import sync_engine


class SyncHandler(FileSystemEventHandler):

    def _ignored(self, path: str) -> bool:
        name = Path(path).name
        return any(
            name.endswith(p.lstrip("*")) or name == p
            for p in sync_engine.cfg.get("exclude_patterns", [])
        )

    def _trigger(self, event, label: str):
        if (not event.is_directory
                and not self._ignored(event.src_path)):
            logging.info(f"{label}: {event.src_path}")
            threading.Thread(
                target=sync_engine.sync_to_s3,
                args=(label,), daemon=True
            ).start()

    def on_created(self, e):  self._trigger(e, "CREATED")
    def on_modified(self, e): self._trigger(e, "MODIFIED")
    def on_deleted(self, e):  self._trigger(e, "DELETED")
    def on_moved(self, e):    self._trigger(e, "MOVED")
