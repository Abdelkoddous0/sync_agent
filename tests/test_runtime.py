import os
from pathlib import Path
import subprocess
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def test_runtime_singleton_stop_and_stale_files(tmp_path):
    import runtime
    guard=runtime.RuntimeGuard(tmp_path)
    assert guard.acquire()
    assert runtime.is_running(tmp_path)
    second=runtime.RuntimeGuard(tmp_path)
    assert not second.acquire()
    def release():
        assert guard.stop_event.wait(3)
        guard.close()
    thread=threading.Thread(target=release); thread.start()
    assert runtime.request_stop(timeout=3,data_dir=tmp_path)
    thread.join()
    assert not runtime.is_running(tmp_path)
    assert runtime.request_stop(timeout=0,data_dir=tmp_path)
    third=runtime.RuntimeGuard(tmp_path)
    assert third.acquire()
    time.sleep(.2)
    assert not third.stop_event.is_set()
    third.close()

def test_single_worker_retains_event_during_active_sync(tmp_path):
    from test_sync_engine import FakeStore, make_engine
    store=FakeStore(); engine=make_engine(tmp_path,store)
    entered=threading.Event(); proceed=threading.Event(); twice=threading.Event()
    calls=[]; active=[]
    def sync():
        assert not active
        active.append(True); calls.append(1)
        if len(calls)==1:
            entered.set(); assert proceed.wait(3)
        else: twice.set()
        active.pop()
        return {}
    engine.sync=sync; engine.start()
    assert entered.wait(3)
    for _ in range(10): engine.request_sync()
    proceed.set()
    assert twice.wait(3)
    assert engine.stop(3)
    assert len(calls)==2
    assert engine.request_sync() is False

def test_trailing_debounce_waits_after_last_event(tmp_path):
    from test_sync_engine import FakeStore, make_engine
    engine=make_engine(tmp_path,FakeStore(),debounce_secs=.12)
    initial=threading.Event(); later=threading.Event(); times=[]
    def sync():
        times.append(time.monotonic())
        (initial if len(times)==1 else later).set()
    engine.sync=sync; engine.start(); assert initial.wait(3)
    engine.request_sync(); time.sleep(.08); engine.request_sync()
    last=time.monotonic(); assert later.wait(3)
    assert times[-1]-last>=.10
    assert engine.stop(3)

def test_runtime_cross_process_abrupt_exit_releases_lock(tmp_path):
    import runtime
    code='import runtime,sys; g=runtime.RuntimeGuard(sys.argv[1]); assert g.acquire(); print("ready",flush=True); sys.stdin.readline()'
    proc=subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,text=True,cwd=Path(__file__).resolve().parents[1]/'src')
    try:
        assert proc.stdout.readline().strip()=='ready'
        assert runtime.is_running(tmp_path)
        proc.kill(); proc.wait(timeout=3)
        assert not runtime.is_running(tmp_path)
        guard=runtime.RuntimeGuard(tmp_path); assert guard.acquire(); guard.close()
    finally:
        if proc.poll() is None: proc.kill(); proc.wait()

def test_agent_coordinates_public_api_and_stops_cleanly(tmp_path, monkeypatch):
    import types, config
    monkeypatch.setattr(config,'DATA_DIR',tmp_path/'data')
    monkeypatch.setattr(config,'LOG_DIR',tmp_path/'logs')
    monkeypatch.setattr(config,'validate_config',lambda c:c)
    import sync_engine
    workers=[]; observed=[]
    class Worker:
        def __init__(self,cfg): self.last_report={}; workers.append(self)
        def sync(self): return {}
        def start(self): self.started=True
        def request_sync(self,*a,**kw): pass
        def stop(self,timeout=30): self.stopped=True; return True
    class Observer:
        def schedule(self,handler,path,recursive): observed.append((handler,path,recursive))
        def start(self): pass
        def stop(self): self.stopped=True
        def join(self,timeout=None): pass
    monkeypatch.setattr(sync_engine,'SyncEngine',Worker)
    monkeypatch.setitem(sys.modules,'watchdog',types.ModuleType('watchdog'))
    monkeypatch.setitem(sys.modules,'watchdog.observers',types.SimpleNamespace(Observer=Observer))
    monkeypatch.setitem(sys.modules,'watchdog.events',types.SimpleNamespace(FileSystemEventHandler=object))
    def tray(cfg,request_sync,stop_event):
        assert workers[0].started
        stop_event.set()
    monkeypatch.setitem(sys.modules,'tray',types.SimpleNamespace(run_tray=tray))
    import agent
    cfg={'local_path':str(tmp_path),'workstation_id':'test'}
    assert agent.run_agent(cfg)==0
    assert workers[0].stopped and observed
    import runtime
    assert not runtime.is_running()

def test_watcher_directory_moves_and_filtered_destination(tmp_path,monkeypatch):
    import types
    monkeypatch.setitem(sys.modules,'watchdog.events',types.SimpleNamespace(FileSystemEventHandler=object))
    import watchers
    requests=[]
    handler=watchers.SyncHandler(lambda *a,**k:requests.append(a),
                                {'local_path':str(tmp_path),'exclude_patterns':['*.tmp']})
    event=types.SimpleNamespace(src_path=str(tmp_path/'a.tmp'),dest_path=str(tmp_path/'a.txt'),is_directory=False)
    handler.on_moved(event)
    handler.on_deleted(types.SimpleNamespace(src_path=str(tmp_path/'folder'),is_directory=True))
    assert len(requests)==2
