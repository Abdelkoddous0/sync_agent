"""OPT-IN native Windows tests against a real built bundle, never a fake EXE.

Run only in a disposable Windows account/VM. This suite briefly modifies the
current user's SyncAgent Run entry, but refuses to touch an existing entry.
No AWS calls, browser login, MSI downloads or background sync are performed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

pytestmark=pytest.mark.skipif(os.name!='nt' or not os.environ.get('SYNC_AGENT_TEST_BUNDLE'),
    reason='Requires Windows and explicit SYNC_AGENT_TEST_BUNDLE opt-in (disposable account)')


def test_native_frozen_install_upgrade_uninstall_preserves_data(tmp_path):
    import winreg
    bundle=Path(os.environ['SYNC_AGENT_TEST_BUNDLE']).resolve()
    assert (bundle/'SyncAgent.exe').is_file(), 'Build the complete real Windows bundle first'
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    runkey=r'Software\Microsoft\Windows\CurrentVersion\Run'
    def startup():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,runkey) as key:
                return winreg.QueryValueEx(key,'SyncAgent')[0]
        except FileNotFoundError:
            return None
    assert startup() is None, 'Refusing native acceptance with an existing SyncAgent startup entry'
    uninstall_key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SyncAgent'
    def installed_apps_entry():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,uninstall_key) as key:
                return winreg.QueryValueEx(key,'UninstallString')[0]
        except FileNotFoundError:
            return None
    assert installed_apps_entry() is None, 'Refusing native acceptance with an existing Installed apps entry'
    root=tmp_path/'Local AppData 測試'; root.mkdir()
    roaming=tmp_path/'Roaming'; roaming.mkdir()
    shortcut=roaming/'Microsoft'/'Windows'/'Start Menu'/'Programs'/'Sync Agent.lnk'
    env=dict(os.environ,LOCALAPPDATA=str(root),APPDATA=str(roaming),AWS_EC2_METADATA_DISABLED='true')
    app=root/'Programs'/'SyncAgent'
    expected='"'+str(app/'SyncAgent.exe')+'" --background'
    def run(args,code=0):
        result=subprocess.run([str(x) for x in args],env=env,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=120,input='')
        assert result.returncode==code, (result.stdout,result.stderr)
        return result
    def install():
        run([powershell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
             bundle/'install.ps1','-SourceDir',bundle,'-Yes'])
    try:
        run([bundle/'SyncAgent.exe','--help'])
        run([bundle/'SyncAgent.exe','--status'])
        run([bundle/'SyncAgent.exe','--background'],code=1)
        run([bundle/'SyncAgent.exe','--login'],code=1)
        install()
        assert json.loads((app/'SyncAgent.install.json').read_text(encoding='utf-8-sig'))=={'product':'SyncAgent','schema':1}
        assert startup()==expected
        assert shortcut.is_file()
        assert str(app/'SyncAgent.exe') in installed_apps_entry()
        run([app/'SyncAgent.exe','--status'])
        local=tmp_path/'Synced files'; local.mkdir()
        (local/'valuable.txt').write_text('preserve local file',encoding='utf-8')
        data=root/'SyncAgent'; data.mkdir(exist_ok=True)
        cfg={'workstation_id':'native-test','local_path':str(local),'s3_bucket':'example-test-bucket',
             's3_prefix':'native-acceptance','region':'eu-central-1','autostart':False}
        configfile=data/'config.json'; configfile.write_text(json.dumps(cfg),encoding='utf-8')
        baseline=data/'baseline-acceptance.json'; baseline.write_text('preserve baseline',encoding='utf-8')
        config_before=configfile.read_bytes()
        # Actual second installation exercises upgrade/stop/frozen-file replacement.
        install()
        assert configfile.read_bytes()==config_before
        assert startup()==expected
        uninstall=tmp_path/'uninstall-outside-application.ps1'
        shutil.copy2(app/'uninstall.ps1',uninstall)
        # Run outside the application tree so removal does not depend on its script handle.
        run([powershell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',uninstall,'-Yes'])
        assert not app.exists()
        assert startup() is None
        assert not shortcut.exists() and installed_apps_entry() is None
        assert configfile.read_bytes()==config_before
        assert baseline.read_text(encoding='utf-8')=='preserve baseline'
        assert (local/'valuable.txt').read_text(encoding='utf-8')=='preserve local file'
    finally:
        # Never remove an entry changed by some other process during this test.
        if startup()==expected:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,runkey,0,winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key,'SyncAgent')
        if str(app) in (installed_apps_entry() or ''):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER,uninstall_key)


def test_native_windows_junction_is_rejected(tmp_path):
    import config
    target=tmp_path/'target'; target.mkdir()
    junction=tmp_path/'junction'
    result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(junction),str(target)],
                          capture_output=True,timeout=20)
    assert result.returncode==0, 'Native acceptance requires junction creation support'
    try:
        with pytest.raises(ValueError,match='reparse'):
            config.validate_config({'workstation_id':'junction-test','local_path':str(junction),
                's3_bucket':'example-test-bucket','s3_prefix':'native-acceptance'})
    finally:
        junction.rmdir()
