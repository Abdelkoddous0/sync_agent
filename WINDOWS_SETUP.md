# Windows 10/11: build, set up and test Sync Agent

This is a source-to-Windows test guide, not a claim that Windows or live AWS acceptance has passed. Use a disposable account/VM, a disposable local folder and a non-production S3 bucket/prefix first. Keep deletion propagation OFF. Keep the entire source folder, including `tests` and the PowerShell scripts.

## 1. Build (source machine)

Install 64-bit Python 3.12, including the Python launcher. Open **Command Prompt (cmd)** in the extracted source directory, then run:

```bat
build.bat
```

Stop if the build reports a failed test or packaging error. The complete output folder is `dist\SyncAgent`; do not copy only `SyncAgent.exe`. Target machines running the finished bundle do not need Python.

Before installing for ordinary use, run the opt-in packaged acceptance tests in the disposable account as described in [ACCEPTANCE.md](ACCEPTANCE.md). Those tests refuse an existing SyncAgent startup entry and temporarily modify that entry themselves.

## 2. Install (target Windows account)

From the source directory after a successful build, or from the full output bundle, run in cmd:

```bat
install.bat -NoStartup
```

Review and confirm the destination. `-NoStartup` is recommended for initial testing so Windows login does not start an unconfigured agent. Install normally as the signed-in user, not from an administrator account. Native AWS MSI elevation/per-user behavior still needs testing.

The application goes to `%LOCALAPPDATA%\Programs\SyncAgent`. Settings, logs and baselines live separately in `%LOCALAPPDATA%\SyncAgent`.

## 3. Choose authentication

The application requires AWS CLI. Interactive setup checks for it and offers the official download/install if it is absent. You must approve installation; background mode never installs it. If using an organization-managed profile, provision it before completing the wizard.

### Access keys

Run setup and choose **1 — Access keys**. Supply an access key/secret and, for temporary credentials, the session token. The wizard uses the dedicated `sync-agent` profile and saves new credentials only after confirmation. Avoid long-lived keys when your organization offers SSO or certificate-based access. Shared AWS credential files are not encrypted storage.

### IAM Identity Center / browser SSO

Your AWS administrator must first grant account/role access to the test bucket. With AWS CLI installed, configure an organization-managed profile in cmd:

```bat
aws configure sso --profile company-sso
```

If `aws` is not recognized immediately after installation, open a new terminal or use the full AWS CLI path reported by the installer. If you used Sync Agent setup to install the CLI, cancel the remaining wizard until your SSO profile has been configured, then run setup again.

Choose **2 — Browser SSO** and enter `company-sso`. Approve saving settings, then approve browser sign-in when offered. You can explicitly sign in again later with `--login`.

### Roles Anywhere / other profiles / workload chain

- **3 — Roles Anywhere:** your administrator must provision the trusted signing helper, certificate/private key and AWS role/profile. Select its existing `credential_process` profile. Sync Agent does not install or authenticate the helper; inspect and trust the configured command before using it.
- **4 — Workload/default SDK chain:** no explicit profile is selected. This is mainly for AWS-hosted workloads, not a way to give an ordinary Windows PC an IAM role automatically. Environment/default-profile credentials may take precedence; it is not role-only mode.
- **5 — Other existing profile:** select a trusted SDK-supported profile. Its configuration can execute local credential helper programs when credentials are requested.

Non-key choices do not rewrite shared AWS profile files. Browser login can update AWS token caches. STS identity success does not prove S3 permissions. Profile validation itself does not execute credential helpers; identity checks and synchronization can. A hung credential helper is not bounded by the SDK's connection/read timeouts: verify that your trusted helper runs noninteractively before unattended use.

## 4. Run setup

In cmd:

```bat
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --setup
```

Choose a workstation ID, authentication, region, disposable local folder, test bucket and an isolated prefix such as `sync-agent-test/ws01`. The bucket must already exist. A prefix is not an `s3://` URL and must not begin or end with `/`.

For initial testing:

- Use a new local test folder outside the application/settings folders.
- Use an empty test prefix to avoid first-sync conflicts.
- Keep both deletion options OFF.
- Leave automatic startup OFF until the basic tests pass.
- Review settings before saving. Only start synchronization when ready for actual S3 reads/writes and possible charges.

## 5. Check and operate

Use full paths in cmd; the installer does not add Sync Agent to PATH:

```bat
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --check-auth
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --status
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --background
```

`--check-auth` contacts AWS STS and may execute a trusted configured credential helper. `--background` starts actual synchronization and the tray; do not use it merely to inspect settings. If the wizard already started the agent, do not start another instance. Use the tray's **Sync now**, status and logs controls.

For an expired SSO session:

```bat
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --login
```

For diagnostics or maintenance:

```bat
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --logs
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --reconfigure
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --stop
```

Enable current-user login startup later through reconfiguration's sync/startup options. Saving reconfiguration cooperatively stops the running agent and offers restart. Cancellation leaves it running.

## 6. Test before valuable data

Follow [ACCEPTANCE.md](ACCEPTANCE.md) separately on Windows 10 and Windows 11. Record actual exit codes and observed behavior; redact all credentials/tokens.

At minimum, test upload, download, simultaneous-change conflict preservation, default deletion behavior and restart. First sync treats a same-name path present on both sides as a conflict, even if bytes might match. Do not delete baselines to bypass conflicts or authentication-migration refusals; preserve both sides and review migration deliberately. Keep independent backups.

## 7. Uninstall

```bat
"%LOCALAPPDATA%\Programs\SyncAgent\SyncAgent.exe" --uninstall
```

Confirm removal. Uninstallation preserves local sync data, S3 data, settings, logs, baselines, AWS CLI and shared AWS credentials. Review retained credentials separately if the account or machine is being retired.
