"""Execute real lifecycle scripts in temp trees; process/registry boundaries are mocked."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
PWSH=os.environ.get('SYNC_AGENT_TEST_PWSH') or shutil.which('pwsh') or shutil.which('powershell')
pytestmark=pytest.mark.skipif(not PWSH,reason='PowerShell required for lifecycle behavioral tests')
MARKER='SyncAgent.install.json'


def literal(value):
    return "'"+str(value).replace("'","''")+"'"


def fixture_tree(tmp_path,marked=False):
    app=tmp_path/'profile'/'Programs'/'SyncAgent'
    app.mkdir(parents=True)
    (app/'SyncAgent.exe').write_text('old offline fixture, never executed')
    (app/'keep.txt').write_text('existing user content')
    if marked: (app/MARKER).write_text(json.dumps({'product':'SyncAgent','schema':1}))
    source=tmp_path/'bundle'; source.mkdir()
    for name in ['SyncAgent.exe','install.ps1','uninstall.ps1','ensure_aws_cli.ps1']:
        (source/name).write_text('new offline fixture, never executed')
    return app,source


def run_script(tmp_path,name,source=None,fail_registry=False,harness_dir=None):
    # Windows PowerShell 5.1 cannot run a script from a path longer than MAX_PATH.
    harness=(harness_dir or tmp_path)/'harness.ps1'
    prelude='''$ErrorActionPreference='Stop'
$global:registryValue='old-startup-value'
function Start-Process { param($FilePath,$ArgumentList,[switch]$PassThru,[switch]$NoNewWindow)
    $p=[pscustomobject]@{ExitCode=0;Handle=1}
    $p | Add-Member ScriptMethod WaitForExit { param($Timeout) return $true }
    return $p
}
function Get-ItemPropertyValue { param($LiteralPath,$Name,$ErrorAction) return $global:registryValue }
function Remove-ItemProperty { param($LiteralPath,$Name,$ErrorAction) $global:registryValue=$null }
function Set-ItemProperty { param($LiteralPath,$Name,$Value)
    if ($env:FAIL_REGISTRY -eq '1') { throw 'injected registry failure including rollback' }
    $global:registryValue=$Value
}
function New-Item {
    param($Path,$ItemType,[switch]$Force)
    if ($Path -like 'HKCU:*') { return }
    Microsoft.PowerShell.Management\\New-Item @PSBoundParameters
}
'''
    command='& '+literal(ROOT/'scripts'/name)+' -Yes'
    if source: command+=' -SourceDir '+literal(source)
    harness.write_text(prelude+command+'\n',encoding='utf-8')
    env={**os.environ,'LOCALAPPDATA':str(tmp_path/'profile'),'FAIL_REGISTRY':'1' if fail_registry else '0'}
    return subprocess.run([PWSH,'-NoProfile','-NonInteractive','-File',str(harness)],env=env,
                          text=True,capture_output=True,timeout=30)


def test_installer_refuses_unrecognized_destination_without_touching_it(tmp_path):
    app,source=fixture_tree(tmp_path)
    result=run_script(tmp_path,'install.ps1',source)
    assert result.returncode!=0, result.stdout+result.stderr
    assert 'unrecognized' in (result.stdout+result.stderr).lower(),result.stdout+result.stderr
    assert (app/'keep.txt').read_text()=='existing user content'
    assert (app/'SyncAgent.exe').read_text().startswith('old')


def test_registry_rollback_failure_still_restores_original_files(tmp_path):
    app,source=fixture_tree(tmp_path,marked=True)
    result=run_script(tmp_path,'install.ps1',source,fail_registry=True)
    assert result.returncode!=0,result.stdout+result.stderr
    assert 'injected registry failure' in result.stderr,result.stderr
    assert (app/'keep.txt').read_text()=='existing user content'
    assert (app/'SyncAgent.exe').read_text().startswith('old')


@pytest.mark.parametrize('script',['install.ps1','uninstall.ps1'])
@pytest.mark.parametrize('relation',['same','child','parent'])
def test_lifecycle_refuses_sync_folder_overlap(tmp_path,script,relation):
    app,source=fixture_tree(tmp_path,marked=True)
    data=tmp_path/'profile'/'SyncAgent'; data.mkdir()
    sync={'same':app,'child':app/'files','parent':app.parent}[relation]
    (data/'config.json').write_text(json.dumps({'local_path':str(sync)}))
    result=run_script(tmp_path,script,source if script=='install.ps1' else None)
    assert result.returncode!=0,result.stdout+result.stderr
    assert 'overlap' in (result.stdout+result.stderr).lower(),result.stdout+result.stderr
    assert (app/'keep.txt').read_text()=='existing user content'


def test_installer_rejects_overlong_startup_command(tmp_path):
    deep=tmp_path/('a'*100)/('b'*100)
    app,source=fixture_tree(deep,marked=True)
    result=run_script(deep,'install.ps1',source,harness_dir=tmp_path)
    assert result.returncode!=0,result.stdout+result.stderr
    assert '260' in result.stdout+result.stderr
    assert (app/'keep.txt').exists()


@pytest.mark.parametrize('script',['install.ps1','uninstall.ps1'])
def test_unreadable_configuration_cannot_bypass_overlap_protection(tmp_path,script):
    app,source=fixture_tree(tmp_path,marked=True)
    data=tmp_path/'profile'/'SyncAgent'; data.mkdir()
    (data/'config.json').write_text('{invalid json')
    result=run_script(tmp_path,script,source if script=='install.ps1' else None)
    assert result.returncode!=0,result.stdout+result.stderr
    assert 'cannot verify' in (result.stdout+result.stderr).lower(),result.stdout+result.stderr
    assert (app/'keep.txt').exists()


def test_owned_install_and_uninstall_preserve_settings_and_sync_data(tmp_path):
    app,source=fixture_tree(tmp_path,marked=True)
    data=tmp_path/'profile'/'SyncAgent'; data.mkdir()
    local=tmp_path/'files'; local.mkdir()
    (local/'valuable.txt').write_text('keep synced content')
    settings=json.dumps({'local_path':str(local)})
    (data/'config.json').write_text(settings)
    (data/'baseline-fixture.json').write_text('retained baseline')
    installed=run_script(tmp_path,'install.ps1',source)
    assert installed.returncode==0,installed.stdout+installed.stderr
    assert (app/'SyncAgent.exe').read_text().startswith('new')
    assert json.loads((app/MARKER).read_text(encoding='utf-8-sig'))=={'product':'SyncAgent','schema':1}
    removed=run_script(tmp_path,'uninstall.ps1')
    assert removed.returncode==0,removed.stdout+removed.stderr
    assert not app.exists()
    assert (data/'config.json').read_text()==settings
    assert (data/'baseline-fixture.json').read_text()=='retained baseline'
    assert (local/'valuable.txt').read_text()=='keep synced content'


def test_uninstaller_refuses_unrecognized_destination(tmp_path):
    app,_=fixture_tree(tmp_path)
    result=run_script(tmp_path,'uninstall.ps1')
    assert result.returncode!=0,result.stdout+result.stderr
    assert (app/'keep.txt').exists()
