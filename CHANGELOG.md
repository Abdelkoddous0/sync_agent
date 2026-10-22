# Changelog

All notable changes to Sync Agent. Dates are YYYY-MM-DD.

## [Unreleased]

### Fixed
- Installation failed on every real Windows machine. Three separate causes:
  - Windows PowerShell 5.1 reported an empty exit code for `Start-Process -PassThru`.
  - `Get-ItemPropertyValue` threw on a missing startup value even with `-ErrorAction SilentlyContinue`.
  - Console symbols crashed `SyncAgent.exe` when the installer captured its output.
- The tray's confirmation dialog appeared but could not be clicked; windows opened from the tray did not receive keyboard focus.
- The setup window could disappear while waiting for input, and on Windows 11 the agent left a terminal window open. The agent now always starts without a window.
- Downloads were limited to `transfer_timeout` in total, so large files failed on every pass; the limit now applies to stalls only.
- AWS profile validation started a process (`cmd /c ver`) despite being a local-only check.
- Uninstall and upgrade could fail while the just-stopped agent still held its files.
- `[y/N]` hints were hidden in yes/no prompts that default to *No*.
- The `notifications` setting had no effect.
- The test suite failed on native Windows (symlink privilege, long paths), which blocked `build.bat`.

### Added
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
