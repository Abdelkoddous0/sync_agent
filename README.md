# ⚙️ HTE Sync Agent

> **AWS S3 Bidirectional Sync Agent for Windows**
> Replaces SyncTrayzor / SyncThing with direct AWS S3 sync.
> Runs silently in the system tray. Auto-starts on Windows login.

![Version](https://img.shields.io/badge/version-3.3.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [File Structure](#file-structure)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Build](#build)
- [Installation](#installation)
- [First-Time Setup](#first-time-setup)
- [Agent Runtime](#agent-runtime)
- [System Tray](#system-tray)
- [CLI Commands](#cli-commands)
- [Reconfiguration](#reconfiguration)
- [Configuration Reference](#configuration-reference)
- [Auto Start](#auto-start)
- [Bidirectional Sync](#bidirectional-sync)
- [Error Handling](#error-handling)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)

---

## Overview

HTE Sync Agent is a lightweight Windows background service that
watches a local folder in real time and syncs changes directly
to and from AWS S3.

```
Local Folder `<->` AWS S3 Bucket `<->` ELN / HTE Portal
```

Each workstation gets a unique ID and its own isolated S3 folder.
Files deleted from S3 are automatically mirrored to the local folder.

---

## Features

| Feature | Description |
|---|---|
| Bidirectional sync | Local to S3 on file change and S3 to local on poll |
| Delete mirroring | Deletions sync in both directions |
| CLI setup wizard | Interactive terminal wizard on first run |
| Partial reconfigure | Change only the settings you need |
| System tray | Silent background agent with color-coded status |
| Auto-start | VBS launcher registers Windows Scheduled Task |
| Live logs | Color-coded PowerShell terminal |
| Uninstall | Full removal from tray or CLI |
| No Python needed | Self-contained PyInstaller bundle |

---

## File Structure

```
HTESync/
├── main.py              Entry point and argument parser
├── agent.py             launch_agent() coordinator
├── config.py            Paths, load/save, startup, console
├── helpers.py           Rich CLI helpers and AWS verify
├── sync_engine.py       Global state, push, pull, poller
├── watcher.py           FileSystemWatcher handler
├── tray.py              Tray icon, menu and all actions
├── wizard.py            Full first-time setup wizard
├── reconfigure.py       Partial reconfiguration menu
├── commands.py          Status, logs, uninstall commands
├── requirements.txt     pip dependencies
├── build.bat            PyInstaller build script
├── install.bat          Deployment installer
├── .gitignore           Git ignore
└── README.md            This file
```

### Deployed Layout

```
C:\Program Files\HTESync\     App bundle (read-only)
    HTESync.exe
    _internal\

C:\ProgramData\HTESync\       Data (always writable)
    config.json
    launch_agent.vbs
    logs\
        sync_ws22.log
```

---

## Architecture

### System Overview

```mermaid
flowchart LR
    subgraph WS[Workstations]
        W1["ws22"]
        W2["ws17"]
        W3["ws_test01"]
    end

    subgraph AGT[HTE Sync Agent]
        FW["File Watcher"]
        DB["Debounce"]
        PUSH["S3 Push"]
        PULL["S3 Pull"]
        TR["Tray Icon"]
        LG["Logger"]
    end

    subgraph S3[AWS S3]
        P1["workstations/ws22"]
        P2["workstations/ws17"]
        P3["workstations/ws_test01"]
    end

    subgraph DST[Downstream]
        ELN["ELN"]
        HTE["HTE Portal"]
    end

    W1 --> FW
    W2 --> FW
    W3 --> FW
    FW --> DB
    DB --> PUSH
    PUSH --> TR
    PUSH --> LG
    PULL --> TR
    PULL --> LG
    PUSH --> P1
    PUSH --> P2
    PUSH --> P3
    P1 --> PULL
    P2 --> PULL
    P3 --> PULL
    PULL --> W1
    PULL --> W2
    PULL --> W3
    P1 --> ELN
    P2 --> ELN
    P3 --> ELN
    P1 --> HTE
    P2 --> HTE
    P3 --> HTE
```

### Module Dependency

```mermaid
flowchart TD
    A["main.py"] --> B["agent.py"]
    A --> C["wizard.py"]
    A --> D["reconfigure.py"]
    A --> E["commands.py"]
    B --> F["sync_engine.py"]
    B --> G["watcher.py"]
    B --> H["tray.py"]
    C --> I["helpers.py"]
    D --> I
    E --> I
    F --> J["config.py"]
    G --> F
    H --> F
    I --> J
    C --> B
    D --> B
```

---

## Prerequisites

### Developer Machine (build once)

| Software | Version | Install |
|---|---|---|
| Python | 3.10+ | [python.org](https://python.org) |
| AWS CLI v2 | Latest | [aws.amazon.com/cli](https://aws.amazon.com/cli) |

### Install Python Packages

```batch
pip install rich watchdog pystray pillow plyer boto3 pyinstaller
```

### Verify

```batch
py -c "import rich;     print('rich     OK')"
py -c "import watchdog; print('watchdog OK')"
py -c "import pystray;  print('pystray  OK')"
py -c "import PIL;      print('pillow   OK')"
py -c "import plyer;    print('plyer    OK')"
py -c "import boto3;    print('boto3    OK')"
aws --version
```

### Target Workstations

```
Required  : Windows 10 or 11
Required  : AWS CLI v2
Required  : Admin rights for install.bat only
Not needed: Python
Not needed: pip
```

---

## Build

```mermaid
flowchart TD
    A["Run build.bat"] --> B{"Python found?"}
    B -->|No| C["Install Python from python.org"]
    B -->|Yes| D["Install pip packages"]
    D --> E["Clean old build"]
    E --> F["Run PyInstaller onedir"]
    F --> G{"Build OK?"}
    G -->|No| H["Fix errors and retry"]
    G -->|Yes| I["dist/HTESync bundle ready"]
    I --> J["Copy to workstation"]
```

```batch
build.bat
```

Output:
```
dist\
    HTESync\
        HTESync.exe
        _internal\
```

---

## Installation

```mermaid
flowchart TD
    A["Run install.bat"] --> B{"Admin rights?"}
    B -->|No| C["Auto UAC elevation"]
    C --> D["Stop old instance"]
    B -->|Yes| D
    D --> E["Remove old install"]
    E --> F["Copy to Program Files"]
    F --> G["Create ProgramData folders"]
    G --> H["Register Scheduled Task via VBS"]
    H --> I["Add Defender exclusions"]
    I --> J["Create Desktop shortcut"]
    J --> K["Add to PATH"]
    K --> L{"Launch now?"}
    L -->|Yes| M["Start agent"]
    L -->|No| N["Done"]
    M --> N
```

```batch
:: Run as Administrator
install.bat
```

### Simple Deployment (no install.bat)

```batch
copy dist\HTESync.exe C:\ProgramData\HTESync\HTESync.exe
C:\ProgramData\HTESync\HTESync.exe
```

### What install.bat Does

| Step | Action |
|---|---|
| 1 | Auto UAC elevation |
| 2 | Stop old running instance |
| 3 | Remove old Program Files install |
| 4 | Deploy bundle to Program Files |
| 5 | Create ProgramData folders |
| 6 | Register Scheduled Task via VBS launcher |
| 7 | Add Windows Defender exclusions |
| 8 | Create Desktop shortcut |
| 9 | Add to system PATH |
| 10 | Optionally launch agent |

---

## First-Time Setup

Runs automatically when `config.json` does not exist.

```mermaid
flowchart TD
    A["No config found"] --> B["Show banner"]
    B --> C["Step 1 - Workstation ID"]
    C --> D{"Valid?"}
    D -->|No| E["Show error"]
    E --> C
    D -->|Yes| F["Step 2 - AWS Credentials"]
    F --> G["Verify with AWS"]
    G --> H{"Valid?"}
    H -->|No| I["Show error and retry"]
    I --> F
    H -->|Yes| J["Step 3 - Sync Paths"]
    J --> K{"Paths provided?"}
    K -->|No| L["Show error"]
    L --> J
    K -->|Yes| M["Step 4 - Options"]
    M --> N["Step 5 - Auto Start"]
    N --> O["Step 6 - Save"]
    O --> P["Configure AWS CLI"]
    P --> Q["Write config.json"]
    Q --> R{"Register task?"}
    R -->|Yes| S["Create VBS and task"]
    R -->|No| T["Show summary"]
    S --> T
    T --> U["Launch agent in tray"]
```

### Setup Fields

| Step | Field | Example | Required |
|---|---|---|---|
| 1 | Workstation ID | ws22 | Yes |
| 2 | AWS Access Key ID | AKIA... | Yes |
| 2 | AWS Secret Key | hidden | Yes |
| 2 | AWS Region | eu-central-1 | Yes |
| 3 | Local Folder | C:\HTE Sync\ws22 | Yes |
| 3 | S3 Bucket | hte-transfer-bucket | Yes |
| 3 | S3 Prefix | workstations/ws22 | Auto |
| 4 | Debounce | 5 seconds | Default 5 |
| 4 | Max Retries | 3 | Default 3 |
| 4 | Delete to S3 | No | Default No |
| 4 | Sync from S3 | Yes | Default Yes |
| 4 | Poll Interval | 30 seconds | Default 30 |
| 4 | Notifications | Yes | Default Yes |
| 4 | Recursive | Yes | Default Yes |
| 4 | Excludes | tmp part | Default set |
| 5 | Auto-Start | Yes | Default Yes |

---

## Agent Runtime

### Startup Sequence

```mermaid
flowchart TD
    A["HTESync.exe launches"] --> B["Hide console window"]
    B --> C["Load config.json"]
    C --> D["Initialize logger"]
    D --> E["Send startup notification"]
    E --> F["Start FileSystemWatcher"]
    F --> G["Start S3 poll thread"]
    G --> H["Run initial push and pull"]
    H --> I["Start tray icon - blocking"]
    I --> J["Agent running silently"]
```

### Watch Loop

```mermaid
flowchart TD
    A["Watching folder"] --> B{"File event?"}
    B -->|No| C["Idle"]
    C --> A
    B -->|Yes| D{"Event type?"}
    D -->|Created| E["Created"]
    D -->|Modified| F["Modified"]
    D -->|Deleted| G["Deleted"]
    D -->|Moved| H["Moved"]
    E --> I{"Excluded?"}
    F --> I
    G --> I
    H --> I
    I -->|Yes| A
    I -->|No| J["Start debounce timer"]
    J --> K{"New event in window?"}
    K -->|Yes| J
    K -->|No| L["Run aws s3 sync push"]
    L --> M{"Result?"}
    M -->|Success| N["Green tray and notify"]
    M -->|Failed| O["Retry logic"]
    N --> A
    O --> A
```

---

## System Tray

### Icon Colors

| Color | Status |
|---|---|
| 🟢 Green | Idle - last sync OK |
| 🟠 Orange | Push or pull in progress |
| 🔴 Red | Failed or auth error |

### Tray Menu

```
Workstation: ws22
Local: C:\HTE Sync\ws22\data
S3: s3://bucket/workstations/ws22/
Status: OK  14:32:01
Pull interval: 30s
─────────────────────
Push to S3 Now
Pull from S3 Now
Show Status
Open Local Folder
View Live Logs
─────────────────────
Reconfigure
Uninstall
─────────────────────
Quit
```

### Tray Menu Flow

```mermaid
flowchart TD
    A["Right-click tray"] --> B["Menu opens"]
    B --> C{"Selection?"}
    C -->|Push to S3 Now| D["Force immediate push"]
    C -->|Pull from S3 Now| E["Force immediate pull"]
    C -->|Show Status| F["Desktop notification"]
    C -->|Open Folder| G["Open Explorer"]
    C -->|View Live Logs| H["Open PowerShell terminal"]
    C -->|Reconfigure| I["Open reconfigure menu"]
    C -->|Uninstall| J["Confirm then uninstall"]
    C -->|Quit| K["Stop agent and exit"]
```

---

## CLI Commands

```mermaid
flowchart LR
    A["HTESync.exe"] --> B{"Argument?"}
    B -->|none| C{"Config exists?"}
    C -->|No| D["Run setup wizard"]
    C -->|Yes| E["Run silent agent"]
    B -->|reconfigure| F["Partial reconfigure menu"]
    B -->|reconfigure-all| G["Full setup wizard"]
    B -->|status| H["Print config table"]
    B -->|logs| I["Open live log terminal"]
    B -->|follow| I
    B -->|uninstall| J["Run uninstall wizard"]
```

### Reference

| Command | Description |
|---|---|
| `HTESync.exe` | Auto wizard or silent agent |
| `HTESync.exe --reconfigure` | Partial reconfigure menu |
| `HTESync.exe --reconfigure-all` | Full setup wizard from scratch |
| `HTESync.exe --status` | Show current configuration |
| `HTESync.exe --logs` | Open live color log terminal |
| `HTESync.exe --follow` | Open live color log terminal |
| `HTESync.exe --uninstall` | Run full uninstall wizard |

---

## Reconfiguration

Change only the settings you need — no need to redo everything.

```mermaid
flowchart TD
    A["HTESync.exe --reconfigure"] --> B["Show current config"]
    B --> C["Show menu"]
    C --> D{"Selection?"}
    D -->|1| E["Workstation Identity"]
    D -->|2| F["AWS Credentials"]
    D -->|3| G["Sync Paths"]
    D -->|4| H["Push Options"]
    D -->|5| I["Pull Options"]
    D -->|6| J["Notifications"]
    D -->|7| K["Exclude Patterns"]
    D -->|8| L["Auto-Start"]
    D -->|A| M["Full setup wizard"]
    D -->|0| N["Save and exit"]
    E & F & G & H & I & J & K & L --> B
    N --> O["Save config and restart agent"]
```

### Menu Options

| Key | Section | What Changes |
|---|---|---|
| 1 | Workstation Identity | workstation_id |
| 2 | AWS Credentials | access key, secret, region |
| 3 | Sync Paths | local_path, s3_bucket, s3_prefix |
| 4 | Push Options | debounce, retries, delete_on_s3, recursive |
| 5 | Pull Options | sync_from_s3, poll_interval |
| 6 | Notifications | notifications on or off |
| 7 | Exclude Patterns | exclude_patterns list |
| 8 | Auto-Start | register or remove task |
| A | All settings | runs full wizard |
| 0 | Save and exit | saves and restarts agent |

---

## Configuration Reference

### Location

```
C:\ProgramData\HTESync\config.json
```

### Full Schema

```json
{
  "workstation_id"   : "ws22",
  "local_path"       : "C:\\HTE Sync\\ws22\\data",
  "s3_bucket"        : "hte-transfer-bucket",
  "s3_prefix"        : "workstations/ws22",
  "region"           : "eu-central-1",
  "debounce_secs"    : 5,
  "max_retries"      : 3,
  "delete_on_s3"     : false,
  "sync_from_s3"     : true,
  "poll_interval"    : 30,
  "notifications"    : true,
  "recursive"        : true,
  "exclude_patterns" : ["*.tmp","*.part","~$*","desktop.ini","Thumbs.db"],
  "log_file"         : "C:\\ProgramData\\HTESync\\logs\\sync_ws22.log"
}
```

### Options

| Key | Type | Default | Description |
|---|---|---|---|
| workstation_id | string | required | Unique machine name |
| local_path | string | required | Folder to watch |
| s3_bucket | string | required | S3 bucket name |
| s3_prefix | string | required | S3 folder path |
| region | string | eu-central-1 | AWS region |
| debounce_secs | int | 5 | Seconds before pushing |
| max_retries | int | 3 | Retry attempts on failure |
| delete_on_s3 | bool | false | Mirror local deletes to S3 |
| sync_from_s3 | bool | true | Enable S3 to local pull |
| poll_interval | int | 30 | Seconds between S3 polls |
| notifications | bool | true | Windows toast alerts |
| recursive | bool | true | Watch subfolders |
| exclude_patterns | list | see above | Files to skip |

---

## Auto Start

### How It Works

```mermaid
flowchart TD
    A["User logs into Windows"] --> B["Task Scheduler fires"]
    B --> C["wscript.exe runs VBS launcher"]
    C --> D["HTESync.exe starts with no window"]
    D --> E["Load config.json"]
    E --> F["Initialize logger"]
    F --> G["Send startup notification"]
    G --> H["Start FileSystemWatcher"]
    H --> I["Start S3 poll thread"]
    I --> J["Run initial push and pull"]
    J --> K["Tray icon appears"]
```

### Task Details

```
Name      : HTESyncAgent_ws22
Trigger   : On user login ONLOGON
Action    : wscript.exe "C:\ProgramData\HTESync\launch_agent.vbs"
Privilege : Highest available
Window    : Hidden - no CMD visible
```

### Task Commands

```batch
schtasks /Query  /TN "HTESyncAgent_ws22" /FO LIST
schtasks /Run    /TN "HTESyncAgent_ws22"
schtasks /Change /TN "HTESyncAgent_ws22" /DISABLE
schtasks /Change /TN "HTESyncAgent_ws22" /ENABLE
schtasks /Delete /TN "HTESyncAgent_ws22" /F
```

---

## Bidirectional Sync

```mermaid
flowchart LR
    A["Local Folder"] -- "File changed - push" --> B["S3 Bucket"]
    B -- "Poll every 30s - pull" --> A
    A -- "File deleted locally" --> B
    B -- "File deleted from S3" --> A
```

### Sync Direction Summary

| Direction | Trigger | Flag |
|---|---|---|
| Local to S3 | File change (real-time) | aws s3 sync LOCAL S3 |
| S3 to Local | Every poll_interval seconds | aws s3 sync S3 LOCAL --delete |
| Delete to S3 | delete_on_s3 = true | --delete on push |
| Delete to Local | sync_from_s3 = true | --delete on pull (always on) |

### Delete Behavior

| delete_on_s3 | sync_from_s3 | Result |
|---|---|---|
| false | false | No deletions mirrored |
| true | false | Local deletes go to S3 |
| false | true | S3 deletes come to local |
| true | true | Full bidirectional mirror |

### Timeline

```
00:00  Agent starts - initial push and pull
00:30  Poll fires - S3 to local check
01:15  File deleted from S3 bucket
01:30  Poll fires - local file removed
```

---

## Error Handling

```mermaid
flowchart TD
    A["Sync fails"] --> B{"Error type?"}
    B -->|Network| C["Retry after 30s"]
    B -->|Auth| D["Stop and notify"]
    B -->|Bucket| E["Stop and notify"]
    B -->|Permission| F["Stop and notify"]
    B -->|File locked| G["Skip and wait"]
    C --> H{"Max retries?"}
    H -->|No| I["Wait 30s and retry"]
    I --> J{"Success?"}
    J -->|Yes| K["Resume normal"]
    J -->|No| H
    H -->|Yes| L["Mark FAILED and notify"]
    D --> M["Red tray icon"]
    E --> M
    F --> M
    L --> M
    M --> N{"User action?"}
    N -->|Push Now| I
    N -->|Reconfigure| O["Open reconfigure"]
    N -->|View Logs| P["Open log terminal"]
```

### Error Reference

| Error | Cause | Retries | Fix |
|---|---|---|---|
| Network timeout | No internet | Yes | Wait for connection |
| InvalidClientTokenId | Wrong Access Key | No | Run --reconfigure |
| SignatureDoesNotMatch | Wrong Secret Key | No | Run --reconfigure |
| NoSuchBucket | Wrong bucket name | No | Run --reconfigure |
| AccessDenied | IAM permissions | No | Fix IAM policy |
| File locked | File in use | Next event | Close the file |

---

## Security

### Minimum IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::hte-transfer-bucket",
        "arn:aws:s3:::hte-transfer-bucket/workstations/*"
      ]
    }
  ]
}
```

### Defender Exclusions Added Automatically

```
Folders  : C:\Program Files\HTESync\
           C:\ProgramData\HTESync\
Process  : HTESync.exe
```

---

## Troubleshooting

```mermaid
flowchart TD
    A["Problem"] --> B{"Symptom?"}
    B -->|No tray icon| C["Check Task Manager for HTESync"]
    B -->|Not syncing| D["Run status then logs"]
    B -->|S3 delete not local| E["Check sync_from_s3 is true"]
    B -->|Local delete not S3| F["Check delete_on_s3 is true"]
    B -->|Wizard fails| G["Delete config and reconfigure"]
    B -->|Defender blocks| H["Run install.bat as Admin"]
    B -->|No auto start| I["Re-run install.bat"]
    B -->|Auth error| J["Run --reconfigure"]
    B -->|Bucket error| K["Run --reconfigure"]
```

### Diagnostic Commands

```batch
tasklist | findstr HTESync
HTESync.exe --status
HTESync.exe --logs
aws sts get-caller-identity
aws s3 ls s3://your-bucket/
schtasks /Query /TN "HTESyncAgent_ws22" /FO LIST
type C:\ProgramData\HTESync\config.json
```

---

## Uninstall

### From Tray

```mermaid
flowchart TD
    A["Tray - Uninstall"] --> B["Windows confirm dialog"]
    B -->|No| C["Cancelled"]
    B -->|Yes| D["Stop poller and watcher"]
    D --> E["Open terminal window"]
    E --> F["Stop agent process"]
    F --> G["Remove scheduled task"]
    G --> H["Remove Defender exclusions"]
    H --> I["Delete Program Files"]
    I --> J{"Keep ProgramData?"}
    J -->|Yes| K["Keep config and logs"]
    J -->|No| L["Delete config and logs"]
    K --> M{"Remove AWS credentials?"}
    L --> M
    M -->|Yes| N["Delete aws folder"]
    M -->|No| O["Keep credentials"]
    N --> P["Remove shortcut"]
    O --> P
    P --> Q["Uninstall complete"]
```

### From CLI

```batch
HTESync.exe --uninstall
```

### Manual Commands

```batch
taskkill /IM HTESync.exe /F
schtasks /Delete /TN "HTESyncAgent_ws22" /F
powershell Remove-MpPreference -ExclusionPath "C:\Program Files\HTESync"
powershell Remove-MpPreference -ExclusionPath "C:\ProgramData\HTESync"
powershell Remove-MpPreference -ExclusionProcess "HTESync.exe"
rmdir /s /q "C:\Program Files\HTESync"
rmdir /s /q "C:\ProgramData\HTESync"
```

---

## Quick Reference

```
PATHS
  App    : C:\Program Files\HTESync\HTESync.exe
  Config : C:\ProgramData\HTESync\config.json
  Logs   : C:\ProgramData\HTESync\logs\
  VBS    : C:\ProgramData\HTESync\launch_agent.vbs

COMMANDS
  HTESync.exe                   Auto wizard or agent
  HTESync.exe --reconfigure     Partial reconfigure menu
  HTESync.exe --reconfigure-all Full setup wizard
  HTESync.exe --status          Show configuration
  HTESync.exe --logs            Live log terminal
  HTESync.exe --uninstall       Uninstall wizard

TRAY COLORS
  Green  = Idle or last sync OK
  Orange = Sync in progress
  Red    = Failed or auth error

SYNC DIRECTION
  Local to S3  = Real-time on file change
  S3 to Local  = Every poll_interval seconds

BUILD AND DEPLOY
  Build   : build.bat on dev machine
  Install : install.bat as Admin on workstation
  Remove  : HTESync.exe --uninstall
```

---

*HTE Sync Agent v3.3 — Clariant HTE Team — 2026*
