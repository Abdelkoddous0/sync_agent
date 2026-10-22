"""Agent coordinator. run_agent(cfg)->int blocks until clean shutdown.

Tray contract: tray.run_tray(cfg, request_sync, stop_event), imported lazily.
All exits stop the observer and serialized worker before releasing the singleton.
A slow/blocked SDK call keeps the instance locked; stop commands time out rather
than killing a process or allowing configuration replacement during a transfer.
"""
import logging
from logging.handlers import RotatingFileHandler
import threading

import sync_engine
from runtime import RuntimeGuard


def run_agent(cfg):
    import config
    cfg = config.validate_config(cfg)
    guard = RuntimeGuard()
    if not guard.acquire():
        logging.warning('Sync Agent is already running')
        return 1
    observer = None
    worker = None
    log_handler = None
    stopper = None
    shutdown_complete = threading.Event()
    try:
        config.LOG_DIR.mkdir(parents=True,exist_ok=True)
        log_handler = RotatingFileHandler(
            cfg.get('log_file',str(config.LOG_DIR/'sync.log')),
            maxBytes=5*1024*1024,backupCount=3,encoding='utf-8')
        log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logging.getLogger().addHandler(log_handler)
        logging.getLogger().setLevel(logging.INFO)
        # boto3 logs "Found credentials in ..." on every client; only its warnings belong in the log.
        logging.getLogger('botocore').setLevel(logging.WARNING)
        logging.info('Sync Agent started: %s <-> s3://%s/%s (sign-in: %s)', cfg.get('local_path'), cfg.get('s3_bucket'),
                     cfg.get('s3_prefix', ''), cfg.get('aws_profile') or cfg.get('auth_method'))
        from watchdog.observers import Observer
        from watchers import SyncHandler
        worker = sync_engine.SyncEngine(cfg)
        sync_engine.cfg = cfg
        sync_engine.engine = worker
        original_sync = worker.sync
        def reported_sync():
            sync_engine.sync_status = 'Syncing'
            report = original_sync()
            sync_engine.sync_status = ('Conflict/Error' if report.get('conflicts') or report.get('errors') else 'Idle')
            try:
                sync_engine.atomic_json(config.DATA_DIR/'status.json',
                                        {'status':sync_engine.sync_status, **report})
            except OSError:
                logging.exception('Could not persist status')
            return report
        worker.sync = reported_sync
        try:
            # Replace any earlier "Startup failed" report before the first pass completes.
            sync_engine.atomic_json(config.DATA_DIR/'status.json',
                                    {'status':'Starting','conflicts':[],'errors':[],'changed':[]})
        except OSError:
            logging.exception('Could not persist status')
        observer = Observer()
        observer.schedule(SyncHandler(worker.request_sync,cfg),path=cfg['local_path'],
                          recursive=cfg.get('recursive',True))
        sync_engine.observer = observer
        observer.start()
        worker.start()
        # Signal SDK cancellation promptly, not only after tray's main loop ends.
        def stop_on_request():
            while not shutdown_complete.wait(.05):
                if guard.stop_event.is_set():
                    worker.stop(timeout=0)
                    return
        stopper = threading.Thread(target=stop_on_request,name='agent-stop',daemon=True)
        stopper.start()
        from tray import run_tray
        run_tray(cfg,worker.request_sync,guard.stop_event)
        return 0
    finally:
        guard.stop_event.set()
        shutdown_complete.set()
        try:
            if observer is not None:
                observer.stop()
                observer.join()  # Lock stays held until watcher really exits.
        finally:
            try:
                if worker is not None:
                    while not worker.stop(timeout=1):
                        pass
                if stopper is not None:
                    stopper.join(2)
            finally:
                sync_engine.engine = None
                sync_engine.observer = None
                guard.close()
                if log_handler:
                    logging.info('Sync Agent stopped')
                    logging.getLogger().removeHandler(log_handler)
                    log_handler.close()


def launch_agent(config=None):
    if config is None:
        from config import load_config
        config = load_config()
    return run_agent(config)
