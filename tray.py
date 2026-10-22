"""Windows tray UI; shell-free actions and cancellation without stopping sync."""
import ctypes
import logging
import os
import subprocess
import threading

import config


def confirm_action(message):
    if os.name != 'nt':
        return False
    return ctypes.windll.user32.MessageBoxW(0,message,config.APP_NAME,0x04|0x30) == 6


def launch_maintenance(mode, stop_event):
    if not confirm_action('Open '+mode.lstrip('-')+'? Sync continues until you confirm the operation in the new window.'):
        return
    # The new command stops the agent only AFTER final confirmation.
    # Cancelling either dialog must not terminate the running agent.
    subprocess.Popen(config.launch_command(mode),creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0),close_fds=True)


def run_tray(cfg, request_sync, stop_event):
    import pystray
    from PIL import Image, ImageDraw
    image = Image.new('RGBA',(64,64),(0,0,0,0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8,8,56,56),fill='#2675bf')
    draw.text((25,22),'S',fill='white')

    def guarded(action):
        def invoke(icon,item):
            try:
                action()
            except Exception as exc:
                logging.error('Tray action failed (%s)',type(exc).__name__)
                icon.notify('Action failed. Check Sync Agent logs.',config.APP_NAME)
        return invoke

    def launch(*args):
        subprocess.Popen(config.launch_command(*args),creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0),close_fds=True)

    def quit_agent():
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem('Workstation: '+cfg['workstation_id'],None,enabled=False),
        pystray.MenuItem('Sync now',guarded(request_sync)),
        pystray.MenuItem('Show status',guarded(lambda: launch('--status'))),
        pystray.MenuItem('Sign in (SSO)',guarded(lambda: launch('--login')),visible=cfg.get('auth_method') == 'sso'),
        pystray.MenuItem('Check AWS identity',guarded(lambda: launch('--check-auth'))),
        pystray.MenuItem('Open local folder',guarded(lambda: os.startfile(cfg['local_path']))),
        pystray.MenuItem('View live logs',guarded(lambda: launch('--logs','--follow'))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Reconfigure',guarded(lambda: launch_maintenance('--reconfigure',stop_event))),
        pystray.MenuItem('Uninstall',guarded(lambda: launch_maintenance('--uninstall',stop_event))),
        pystray.MenuItem('Quit',guarded(quit_agent)))
    icon = pystray.Icon(config.APP_ID,image,config.APP_NAME,menu)

    def watch_stop():
        stop_event.wait()
        icon.stop()

    def ready(tray_icon):
        if stop_event.is_set():
            tray_icon.stop()
            return
        tray_icon.visible = True
        threading.Thread(target=watch_stop,daemon=True,name='tray-stop').start()

    try:
        icon.run(setup=ready)
    finally:
        stop_event.set()
