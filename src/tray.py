"""Windows tray UI; shell-free actions and cancellation without stopping sync."""
import ctypes
import logging
import os
import subprocess
import threading

import config


MB_YESNO, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST = 0x04, 0x30, 0x10000, 0x40000


def confirm_action(message):
    if os.name != 'nt':
        return False
    # The tray's hidden window keeps the foreground after its menu closes; without
    # these flags the box shows up inactive and ignores clicks.
    flags = MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
    return ctypes.windll.user32.MessageBoxW(0,message,config.APP_NAME,flags) == 6


def open_console(command):
    """Open a command in its own console that may take keyboard focus from the tray."""
    if os.name == 'nt':
        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_uint(0xFFFFFFFF))  # ASFW_ANY
    subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0),close_fds=True)


def launch_maintenance(mode, stop_event):
    if not confirm_action('Open '+mode.lstrip('-')+'? Sync continues until you confirm the operation in the new window.'):
        return
    # The new command stops the agent only AFTER final confirmation.
    # Cancelling either dialog must not terminate the running agent.
    open_console(config.launch_command(mode) + (['--pause'] if mode == '--reconfigure' else []))


def run_tray(cfg, request_sync, stop_event):
    import pystray
    import sync_engine
    from icons import draw_icon
    images = {state: draw_icon(64, state) for state in ('idle', 'syncing', 'error')}

    def guarded(action):
        def run(icon):
            try:
                action()
            except Exception as exc:
                logging.error('Tray action failed (%s)',type(exc).__name__)
                icon.notify('Action failed. Check Sync Agent logs.',config.APP_NAME)
        def invoke(icon,item):
            # pystray calls this inside its window procedure; a dialog opened there
            # blocks the tray and cannot be activated, so run actions elsewhere.
            threading.Thread(target=run,args=(icon,),daemon=True,name='tray-action').start()
        return invoke

    def launch(*args):
        open_console(config.launch_command(*args))

    def quit_agent():
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem('Workstation: '+cfg['workstation_id'],None,enabled=False),
        pystray.MenuItem('Sync now',guarded(request_sync)),
        # --pause keeps the new console open so its result can be read.
        pystray.MenuItem('Show status',guarded(lambda: launch('--status','--pause'))),
        pystray.MenuItem('Sign in (SSO)',guarded(lambda: launch('--login','--pause')),visible=cfg.get('auth_method') == 'sso'),
        pystray.MenuItem('Check AWS identity',guarded(lambda: launch('--check-auth','--pause'))),
        pystray.MenuItem('Open local folder',guarded(lambda: os.startfile(cfg['local_path']))),
        pystray.MenuItem('View live logs',guarded(lambda: launch('--logs','--follow'))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Reconfigure',guarded(lambda: launch_maintenance('--reconfigure',stop_event))),
        pystray.MenuItem('Uninstall',guarded(lambda: launch_maintenance('--uninstall',stop_event))),
        pystray.MenuItem('Quit',guarded(quit_agent)))
    icon = pystray.Icon(config.APP_ID,images['idle'],config.APP_NAME,menu)

    def watch_stop():
        stop_event.wait()
        icon.stop()

    def watch_status():
        # Amber dot while a pass runs, red dot after conflicts/errors; see --status for details.
        shown = 'idle'
        while not stop_event.wait(1):
            status = sync_engine.sync_status
            state = {'Syncing': 'syncing', 'Conflict/Error': 'error'}.get(status, 'idle')
            if state != shown:
                if state == 'error' and cfg.get('notifications', True):
                    try:
                        icon.notify('A sync pass reported conflicts or errors. Open Show status for details.',
                                    config.APP_NAME)
                    except Exception:
                        logging.debug('Notification unavailable', exc_info=True)
                shown = state
                icon.icon = images[state]
                icon.title = f'{config.APP_NAME} — ' + {'syncing': 'syncing', 'error': 'needs attention (see status)',
                                                        'idle': 'up to date'}[state]

    def ready(tray_icon):
        if stop_event.is_set():
            tray_icon.stop()
            return
        tray_icon.visible = True
        threading.Thread(target=watch_stop,daemon=True,name='tray-stop').start()
        threading.Thread(target=watch_status,daemon=True,name='tray-status').start()

    try:
        icon.run(setup=ready)
    finally:
        stop_event.set()
