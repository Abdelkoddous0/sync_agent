"""Console presentation for Sync Agent. Falls back to plain text without rich.

Presentation only: no settings, credentials or AWS calls. Secret prompts use
getpass so typed values are never echoed or recorded.
"""
from contextlib import contextmanager
import getpass

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    console = Console(highlight=False)
except ImportError:  # Plain fallback keeps diagnostics usable in a broken bundle.
    console = None

ACCENT = 'dodger_blue2'
VERSION = '1.1.0'


def _plain(message):
    print(message)


def banner(subtitle='Windows 10/11 S3 synchronization'):
    if console is None:
        return _plain(f'\nSync Agent {VERSION} — {subtitle}\n')
    title = Text.assemble((' ◆ Sync Agent ', f'bold {ACCENT}'), (f'v{VERSION}', 'dim'))
    console.print()
    console.print(Panel(Text(subtitle, style='white'), title=title, title_align='left',
                        border_style=ACCENT, box=box.ROUNDED, padding=(0, 2), expand=False))


def step(number, total, title, hint=''):
    if console is None:
        return _plain(f'\n[{number}/{total}] {title}' + (f' — {hint}' if hint else ''))
    console.print()
    console.rule(Text.assemble((f' Step {number}/{total} ', f'bold white on {ACCENT}'),
                               (f'  {title}', f'bold {ACCENT}')), align='left', style='grey37')
    if hint:
        console.print(f'  [dim]{hint}[/]')


def section(title):
    if console is None:
        return _plain(f'\n== {title} ==')
    console.print()
    console.rule(f'[bold {ACCENT}]{title}', align='left', style='grey37')


def ok(message):
    if console is None:
        return _plain(f'OK: {message}')
    console.print(f'  [bold green]✔[/] {_escape(message)}')


def warn(message):
    if console is None:
        return _plain(f'Warning: {message}')
    console.print(f'  [bold yellow]![/] [yellow]{_escape(message)}[/]')


def err(message):
    if console is None:
        return _plain(f'Error: {message}')
    console.print(f'  [bold red]✘[/] [red]{_escape(message)}[/]')


def info(message):
    if console is None:
        return _plain(message)
    console.print(f'  [grey70]{_escape(message)}[/]')


def _escape(message):
    from rich.markup import escape
    return escape(str(message))


def ask(prompt, default='', password=False):
    if console is None:
        if password:
            return getpass.getpass(f'{prompt}: ').strip()
        value = input(f'{prompt}' + (f' [{default}]' if default else '') + ': ').strip()
        return value or default
    label = f'  [bold]?[/] {_escape(prompt)}'
    if password:
        return console.input(f'{label} [dim](hidden)[/]: ', password=True).strip()
    if default:
        label += f' [dim]({_escape(default)})[/]'
    value = console.input(f'{label}: ').strip()
    return value or default


def confirm(prompt, default=True):
    hint = 'Y/n' if default else 'y/N'
    while True:
        if console is None:
            value = input(f'{prompt} [{hint}]: ').strip().lower()
        else:
            value = console.input(f'  [bold]?[/] {_escape(prompt)} [dim][{hint}][/]: ').strip().lower()
        if not value:
            return default
        if value in ('y', 'yes'):
            return True
        if value in ('n', 'no'):
            return False
        err('Please enter yes or no.')


def menu(options, title=''):
    """Show (key, label, description) rows; selection is read separately via ask()."""
    if console is None:
        if title:
            _plain(title)
        for key, label, description in options:
            _plain(f'  {key}  {label}' + (f' — {description}' if description else ''))
        return
    table = Table(box=None, show_header=False, padding=(0, 1), pad_edge=False)
    table.add_column(style=f'bold {ACCENT}', justify='right')
    table.add_column(style='bold')
    table.add_column(style='dim')
    for key, label, description in options:
        table.add_row(f'  [{key}]', label, description)
    if title:
        console.print(f'  [bold]{_escape(title)}[/]')
    console.print(table)


def _value(value):
    if isinstance(value, bool):
        return '[green]on[/]' if value else '[grey50]off[/]'
    if value is None or value == '':
        return '[grey50]—[/]'
    if isinstance(value, list):
        return _escape(', '.join(str(v) for v in value)) or '[grey50]—[/]'
    return _escape(value)


AUTH_LABELS = {'access_keys': 'Access keys', 'sso': 'Browser SSO', 'roles_anywhere': 'Roles Anywhere',
               'workload_role': 'Workload / default chain', 'profile': 'Existing AWS profile'}

SETTING_GROUPS = [
    ('Identity', [('workstation_id', 'Workstation')]),
    ('AWS', [('auth_method', 'Authentication'), ('aws_profile', 'Profile'), ('region', 'Region')]),
    ('Locations', [('local_path', 'Local folder'), ('s3_bucket', 'S3 bucket'), ('s3_prefix', 'S3 prefix')]),
    ('Sync', [('sync_from_s3', 'Download from S3'), ('recursive', 'Include subfolders'),
              ('delete_on_s3', 'Delete on S3'), ('delete_local', 'Delete locally'),
              ('debounce_secs', 'Debounce (s)'), ('poll_interval', 'Poll interval (s)'),
              ('max_retries', 'Max attempts'), ('transfer_timeout', 'Transfer timeout (s)'),
              ('exclude_patterns', 'Excluded'), ('autostart', 'Start at login')]),
]


def settings_table(cfg, title='Settings'):
    """Render validated settings; unknown/secret fields are never shown."""
    if console is None:
        import json
        return _plain(json.dumps(cfg, indent=2))
    table = Table(title=f'[bold]{_escape(title)}', title_justify='left', box=box.ROUNDED,
                  border_style='grey37', show_header=False, padding=(0, 1))
    table.add_column(style=f'bold {ACCENT}', no_wrap=True)
    table.add_column(style='dim', no_wrap=True)
    table.add_column(overflow='fold')
    for group, fields in SETTING_GROUPS:
        for index, (key, label) in enumerate(fields):
            if key not in cfg:
                continue
            value = _value(AUTH_LABELS.get(cfg[key], cfg[key]) if key == 'auth_method' else cfg[key])
            if key in ('delete_on_s3', 'delete_local') and cfg[key]:
                value = '[bold red]on[/]'
            table.add_row(group if index == 0 else '', label, value)
        table.add_section()
    console.print(table)


def key_values(rows, title=''):
    if console is None:
        if title:
            _plain(title)
        for label, value in rows:
            _plain(f'  {label}: {value}')
        return
    table = Table(box=None, show_header=False, padding=(0, 1), title=title and f'[bold]{_escape(title)}',
                  title_justify='left')
    table.add_column(style='dim', no_wrap=True)
    table.add_column(overflow='fold')
    for label, value in rows:
        table.add_row(f'  {label}', value if isinstance(value, Text) else _value(value))
    console.print(table)


def badge(text, good):
    if console is None:
        return text
    return Text(f' {text} ', style='bold white on green4' if good else 'bold white on red3')


@contextmanager
def working(message):
    """Spinner while a bounded operation runs; plain mode prints once."""
    if console is None or not console.is_terminal:
        info(message + '…')
        yield
        return
    with console.status(f'[{ACCENT}]{_escape(message)}…', spinner='dots'):
        yield


def log_line(line):
    """Print one log line with its level highlighted."""
    if console is None:
        return print(line, end='', flush=True)
    style = ('red' if ' ERROR ' in line or ' CRITICAL ' in line else
             'yellow' if ' WARNING ' in line else 'grey70')
    console.print(Text(line.rstrip('\n'), style=style), soft_wrap=True)
