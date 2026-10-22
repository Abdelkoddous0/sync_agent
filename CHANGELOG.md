# Changelog

All notable changes to Sync Agent. Dates are YYYY-MM-DD.

## [Unreleased]

### Fixed
- Installation failed on every real Windows machine. Three separate causes:
  - Windows PowerShell 5.1 reported an empty exit code for `Start-Process -PassThru`.
  - `Get-ItemPropertyValue` threw on a missing startup value even with `-ErrorAction SilentlyContinue`.
  - Console symbols crashed `SyncAgent.exe` when the installer captured its output.
- Reconfigure could silently throw away a new access key. Pressing Enter at the menu after entering keys cancelled; when the saved key was rejected, "Enter new AWS access credentials?" still defaulted to No and the window then closed with an error. Now the saved key is checked first (a rejected key makes "Yes" the default), unsaved changes are shown and make Save the default, cancelling asks before discarding them, and errors return to the menu.
- A failure that repeats on every poll (wrong clock, deleted access key) filled the log with the same `WARNING ClientError` every few seconds. It is now logged once, then as "Still failing: …" every 10 minutes, followed by "Previous sync problems resolved" when it clears.
- The tray's confirmation dialog appeared but could not be clicked; windows opened from the tray did not receive keyboard focus.
- The setup window could disappear while waiting for input, and on Windows 11 the agent left a terminal window open. The agent now always starts without a window.
- Downloads were limited to `transfer_timeout` in total, so large files failed on every pass; the limit now applies to stalls only.
- AWS profile validation started a process (`cmd /c ver`) despite being a local-only check.
- Uninstall and upgrade could fail while the just-stopped agent still held its files.
- `[y/N]` hints were hidden in yes/no prompts that default to *No*.
- The `notifications` setting had no effect.
- The test suite failed on native Windows (symlink privilege, long paths), which blocked `build.bat`.

### Added
- Code signing in `build.bat` and CI (`scripts/sign.ps1`): SHA-256, timestamped; signs the application before it is embedded in the installer. Activated by a `.pfx` or certificate thumbprint, or by the `SIGN_PFX_BASE64` / `SIGN_PFX_PASSWORD` repository secrets.
- `scripts/acceptance-test.ps1`: one-command Windows 10/11 acceptance test of `SyncAgentSetup.exe` (20 checks, isolated, restores existing installations); also run by CI.
- `tests/test_live_e2e.py`: opt-in end-to-end sync test against real S3.
- AWS errors now show their code (e.g. `ClientError(AccessDenied)`) and explain a wrong PC clock, a wrong secret key or an unknown access key.
- Start Menu shortcut and a per-user *Installed apps* entry; uninstall from Windows Settings.
- New application icon; the tray icon shows an amber dot while syncing and a red dot after conflicts or errors, plus a tooltip.
- Starting `SyncAgent.exe` when configured runs it in the tray and closes the window.
- Background start-up failures are shown by `--status` (*Startup failed: …*).
- The setup wizard re-asks only the question that failed validation, lists existing AWS profiles, lets you re-enter rejected keys or a mistyped profile, and accepts `s3://bucket/` input.
- Interactive prepared-settings import offers SSO sign-in.
- Windows notification when a pass ends with conflicts or errors (`notifications`).
- Documentation set in `docs/` with flowcharts and screenshots.

### Changed
- The repository is organized into `src/`, `scripts/`, `examples/` and `docs/`; `pyproject.toml` configures pytest.
- Unchanged files are no longer re-hashed on every poll.
- `build.bat` prefers Python 3.12, refuses 32-bit Python and keeps PyInstaller files in `build/`.
- PyInstaller moved from `requirements.txt` to `requirements-dev.txt`.

### Removed
- `program.bat` (use `build.bat`) and the misspelled `requirments.txt`.

## [1.1.0]

- Rich console visuals and the one-file self-configuring installer `SyncAgentSetup.exe`.
- Five authentication methods: access keys, SSO, Roles Anywhere, workload chain, existing profile.
- Conservative reconciliation engine with a persistent baseline, conditional S3 writes and deletions off by default.
