# Testing Sync Agent

There are three levels of testing, from safest to most realistic:

```mermaid
flowchart LR
    accTitle: Test levels
    accDescr: Offline tests need no AWS and no installation. Native packaged tests install the real build into temporary folders. Live tests use a disposable S3 bucket.
    A["1. Offline suite<br/>pytest, ~30 s<br/>no AWS, no install"] --> B["2. Native packaged tests<br/>real install → upgrade → uninstall<br/>disposable Windows account"]
    B --> C["3. Live S3 + manual checklist<br/>disposable bucket<br/>Windows 10 and 11"]
    classDef work fill:#dbeafe,stroke:#1d4ed8,color:#172554
    class A,B,C work
```

Passing tests at one level is not evidence for the next: mocked tests do not prove native Windows behaviour, and native tests do not prove S3 permissions or real syncing.

## 0. Offline suite (any developer machine)

From the repository root (tests import from `src/` via `pyproject.toml`):

```bat
python -m pip install -r requirements-dev.txt
python -m pytest
```

`build.bat` runs the same suite and stops the build on any failure. Expected result: everything passes. Five tests are skipped unless explicitly enabled: the live S3 test, two native bundle tests, and tests needing symlink privileges.

PowerShell lifecycle tests run the real `scripts\*.ps1` with process, network and registry calls mocked. They use Windows PowerShell 5.1 on Windows, or `SYNC_AGENT_TEST_PWSH=/path/to/pwsh` elsewhere.

### Latest recorded run — 2026-10-22, Windows 11 Home (10.0.26200), Python 3.11, Windows PowerShell 5.1

| Level | Result |
| --- | --- |
| Offline suite | **217 passed**, 6 skipped (opt-in live and native tests, symlink privilege), 21 subtests passed |
| Native packaged tests (`tests/test_native_bundle.py`) | **2 passed**: frozen install, upgrade, uninstall, Start Menu shortcut, Installed apps entry, junction rejection |
| One-command acceptance (`scripts\acceptance-test.ps1`) | **20 / 20 checks passed** on Windows 11, with an existing Sync Agent installation on the same account restored byte-for-byte |
| Code signing pipeline | Verified with a temporary self-signed certificate: both executables signed (SHA-256), timestamped, and still run correctly |
| Manual | Tray actions, the confirmation dialog and keyboard focus exercised; the background agent ran and stopped cleanly |
| **Windows 10** | **Pending**: run `acceptance-test.ps1` on a Windows 10 PC |
| Live S3 (`test_live_s3.py`, `test_live_e2e.py`) | **2 passed** against a disposable bucket in eu-central-1 (access-key profile): conditional create/update/download/delete with stale-ETag rejection, and full end-to-end sync (first-sync conflict, both-direction edits, both-sides conflict, deletion default, restart). No test object left behind. |
| **Real code-signing certificate** | **Pending**: requires a certificate issued to the publisher (see [development.md](development.md#code-signing)) |
| Not covered | AWS CLI download/MSI, real SSO and Roles Anywhere sessions |

## Windows 10 / 11 acceptance in one command (no Python needed)

Copy **`scripts\acceptance-test.ps1`** and **`SyncAgentSetup.exe`** into the same folder on the PC to test, then run in PowerShell or cmd:

```bat
powershell -ExecutionPolicy Bypass -File .\acceptance-test.ps1
```

It installs, configures, starts, stops, upgrades and uninstalls the real application in throwaway folders, prints PASS/FAIL for 20 checks, and saves `acceptance-result.txt` beside the installer: send that file back. It is safe on an ordinary PC:

- your real `%LOCALAPPDATA%` and Start Menu are not used (they point to a temporary folder for the test);
- no AWS request is made (fake credentials, unreachable endpoint);
- the two per-user registry entries it cannot redirect (start at login, Installed apps) are backed up and restored exactly, so an existing Sync Agent installation keeps working;
- everything it created is removed at the end.

```mermaid
flowchart LR
    accTitle: Acceptance script stages
    accDescr: The script checks the installer, installs, checks settings and status, starts and stops the agent, upgrades, uninstalls, then restores and cleans up.
    A["Installer starts<br/>+ signature"] --> B["Install<br/>shortcut, Installed apps"] --> C["Status / settings<br/>background refusal"] --> D["Start in tray<br/>cooperative stop"] --> E["Upgrade<br/>settings kept"] --> F["Uninstall<br/>data kept"] --> G["Restore + clean up<br/>PASS / FAIL report"]
    classDef work fill:#dbeafe,stroke:#1d4ed8,color:#172554
    classDef done fill:#dcfce7,stroke:#15803d,color:#14532d
    class A,B,C,D,E,F work
    class G done
```

Afterwards, confirm the four manual checks printed at the end (wizard prompts, tray icon, clickable dialog, login start). The CI workflow runs the same script on its Windows runner.

## 1. Native packaged tests (disposable Windows account/VM only)

Use separate clean 64-bit Windows 10 and Windows 11 VMs. A GitHub-hosted Windows runner is useful supplemental coverage but is not either desktop OS certification. Do not run the native test in an account with a real Sync Agent installation/startup entry. It refuses an existing `SyncAgent` Run value or Installed-apps entry, uses a temporary LOCALAPPDATA with spaces/non-ASCII and a temporary APPDATA for the Start Menu shortcut, and briefly registers current-user startup and the Installed-apps entry. It does not start a sync worker, download AWS CLI or contact AWS.

Build from the source root in cmd:

```bat
build.bat
```

Then in PowerShell, from the same root:

```powershell
$env:SYNC_AGENT_TEST_BUNDLE = (Resolve-Path .\dist\SyncAgent).Path
.\.venv-build\Scripts\python.exe -m pytest tests/test_native_bundle.py -q
Remove-Item Env:\SYNC_AGENT_TEST_BUNDLE
```

This executes the real frozen executable, actual install/upgrade/uninstall scripts and native HKCU startup readback. It verifies missing-config startup/login refusal, retained settings/baseline/local files, and junction rejection. It does not validate tray rendering, Windows login startup, downloaded MSI or browser authentication.

The Windows GitHub Actions workflow invokes these native tests after packaging, but is manual-only (`workflow_dispatch`). Uploading the source does not trigger a build, and no workflow run is claimed successful here.

## 2. Manual Windows UI/bootstrap matrix

On each clean OS, keep screenshots/results and actual exit codes, never tokens or private keys:

- Start without AWS CLI. Decline installation: verify no AWS CLI was installed. Approve on another clean snapshot: verify official MSI Authenticode/Amazon publisher, installation exit status and successful `aws --version`. Check actual UAC behavior; do not assume per-user MSI behavior from mocked tests.
- Repeat with an existing AWS CLI. Confirm detection does not download or replace it.
- Complete setup with disposable files. Verify tray visibility, folder/log actions, an immediate Sync now request, and second-instance rejection.
- Cancel setup and reconfiguration before saving: compare settings/shared AWS profile bytes and confirm the original agent keeps running. Bootstrap consent is separate from settings-save consent.
- Test SSO using a real administrator-provisioned profile. Before save, no browser login. After confirmation, explicit sign-in works. Expire the session: background mode must not open a browser. Use `--login` or the tray SSO item, then `--check-auth`. Restart the agent if it continues reporting an expired session.
- Test a trusted Roles Anywhere profile with a real administrator-provisioned helper/certificate and correct Windows path quoting. Verify short-lived credentials/refresh and refusal of ambiguous static credentials. The app does not authenticate the helper binary or provision PKI.
- Test the workload/default credential chain only in a deliberately configured AWS workload. Confirm which principal `--check-auth` uses; environment/default-profile credentials may take precedence over a role.
- Log out/in to Windows and verify startup; test enabling/disabling startup via reconfiguration. Inspect HKCU readback.
- Test stop during a slow transfer and an active-operation timeout. No forced process kill, duplicate worker or partially replaced local destination should occur.
- Test cancelled uninstall, successful upgrade/uninstall and injected failure rollback with disposable files. Verify synced data, config, baselines, AWS CLI and unrelated shared profiles remain intact.

## 3. Live S3 conditional-operation test (explicit opt-in)

An AWS administrator must provide a DISPOSABLE bucket and a trusted, already-authenticated profile. No credentials go into this repository or chat. Authorize list/get/put/delete only for `sync-agent-acceptance/*` in that bucket; list must be prefix-scoped. KMS encryption or bucket policies can require further permissions. Test requests can incur charges. With versioning enabled, old versions/delete markers can remain and must be reviewed separately by the bucket owner; this test never purges versions.

PowerShell example, after reviewing the target (replace placeholders):

```powershell
$env:SYNC_AGENT_LIVE_BUCKET = 'YOUR-DISPOSABLE-BUCKET'
$env:SYNC_AGENT_LIVE_PROFILE = 'YOUR-TEST-PROFILE'
$env:SYNC_AGENT_LIVE_AUTH_METHOD = 'profile' # or sso / roles_anywhere
$env:SYNC_AGENT_LIVE_REGION = 'eu-central-1'
$env:SYNC_AGENT_LIVE_S3 = 'I_ACCEPT_TEST_OBJECT_WRITES'
.\.venv-build\Scripts\python.exe -m pytest tests/test_live_s3.py tests/test_live_e2e.py -q
Remove-Item Env:\SYNC_AGENT_LIVE_S3
```

The PC clock must be correct: AWS rejects requests from a clock more than 15 minutes off (`SignatureDoesNotMatch` / `RequestTimeTooSkewed`).

`test_live_e2e.py` runs the real sync engine against a unique `sync-agent-acceptance/e2e-<UUID>/` prefix: first-sync conflict, upload, download into a subfolder, edits in both directions, a both-sides conflict (nothing overwritten), the default "local deletion is not propagated" rule, and a restart that must not resurrect the deleted file. At the end it deletes every object under that prefix with conditional deletes of the ETags it just listed.

This creates a unique `sync-agent-acceptance/<UUID>/conditional-probe.txt`, verifies conditional creation/update/download/deletion and stale-ETag rejection, and reads back object state. Cleanup uses only that exact key and its last successfully returned ETag, never bulk or unconditional deletion. Failed/uncertain requests can leave a tiny test object: the bucket owner must review it. Custom endpoint environment overrides are refused. For workload-chain testing, use `workload_role` and no explicit profile in a controlled workload.

Without the exact opt-in, these tests are skipped. Offline guard tests verify that missing bucket/profile or custom endpoints fail before constructing an S3 client. A passing storage test is not full end-to-end sync acceptance: also exercise first-sync conflicts, both-side edits, deletion defaults, opt-in deletion, restart tombstones, edits during transfers and token expiry with the full application on disposable data.

## Record results honestly

For every run record OS build, Python/package versions, source snapshot/revision, command, exit status and test totals. Mark skipped/native/cloud checks explicitly. Do not count authored tests, PowerShell parsing, fake stores or SDK Stubber runs as executed native Windows/cloud acceptance.
