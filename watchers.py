"""Watchdog events only enqueue work; the engine owns all debounce/serialization."""
import fnmatch
from pathlib import Path
from watchdog.events import FileSystemEventHandler


class SyncHandler(FileSystemEventHandler):
    def __init__(self, request_sync=None, cfg=None):
        super().__init__()
        if request_sync is None or cfg is None:
            import sync_engine
            request_sync = request_sync or sync_engine.request_sync
            cfg = cfg if cfg is not None else sync_engine.cfg
        self.request_sync = request_sync
        self.cfg = cfg

    def _ignored(self, value):
        path = Path(value)
        if path.name.startswith('.sync-agent-'):
            return True
        try:
            name = path.relative_to(self.cfg['local_path']).as_posix()
        except ValueError:
            return True
        return any(fnmatch.fnmatchcase(name,p) or fnmatch.fnmatchcase(path.name,p)
                   for p in self.cfg.get('exclude_patterns',[]))

    def _trigger(self,event,label):
        # Directory deletion/move implies changes to every descendant. An ignored
        # source may move into an included destination, or vice versa.
        if (event.is_directory or not self._ignored(event.src_path)
                or (getattr(event,'dest_path',None) and not self._ignored(event.dest_path))):
            self.request_sync(label)

    def on_created(self,event): self._trigger(event,'created')
    def on_modified(self,event): self._trigger(event,'modified')
    def on_deleted(self,event): self._trigger(event,'deleted')
    def on_moved(self,event): self._trigger(event,'moved')
