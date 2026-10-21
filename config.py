# ================================================================
#  config.py — Paths, load/save, startup registration, console
# ================================================================
import os, sys, json, subprocess, ctypes
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable
                   if getattr(sys, "frozen", False)
                   else __file__).parent.resolve()

DATA_DIR    = Path(
    os.environ.get("ProgramData", "C:\\ProgramData")
) / "HTESync"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR     = DATA_DIR / "logs"
VBS_PATH    = DATA_DIR / "launch_agent.vbs"
PF_DIR      = Path(
    os.environ.get("ProgramFiles", "C:\\Program Files")
) / "HTESync"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── Console visibility ───────────────────────────────────────────
def hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def show_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 1)
        else:
            ctypes.windll.kernel32.AllocConsole()
    except Exception:
        pass


# ── Config file ──────────────────────────────────────────────────
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict):
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


# ── Startup task ─────────────────────────────────────────────────
def register_startup(ws_id: str, exe_path: str) -> bool:
    """Create VBS launcher and register Windows Scheduled Task."""
    try:
        vbs = (
            f'Set WShell = CreateObject("WScript.Shell")\n'
            f'WShell.Run """{exe_path}""", 0, False\n'
        )
        VBS_PATH.write_text(vbs, encoding="utf-8")
        task = f"HTESyncAgent_{ws_id}"
        cmd  = (
            f'schtasks /Create /SC ONLOGON /RL HIGHEST /F '
            f'/TN "{task}" '
            f'/TR "wscript.exe \\"{VBS_PATH}\\""'
        )
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        return res.returncode == 0
    except Exception:
        return False


def remove_startup(ws_id: str):
    subprocess.run(
        f'schtasks /Delete /TN "HTESyncAgent_{ws_id}" /F',
        shell=True, capture_output=True
    )
    VBS_PATH.unlink(missing_ok=True)
