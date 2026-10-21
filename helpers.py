# ================================================================
#  helpers.py — Rich CLI helpers and AWS credential verify
# ================================================================
import os, getpass, subprocess

from rich.console  import Console
from rich.panel    import Panel
from rich.prompt   import Prompt, Confirm
from rich.rule     import Rule
from rich.live     import Live
from rich.spinner  import Spinner

con = Console()


def banner():
    con.print()
    con.print(Panel.fit(
        "[bold cyan]HTE Sync Agent[/]  [dim]v3.3[/]\n"
        "[dim]AWS S3 Bidirectional Sync — Replaces SyncTrayzor[/]",
        border_style="cyan", padding=(0, 4)
    ))
    con.print()


def step(n: int, total: int, title: str):
    con.print()
    con.print(Rule(
        f"[bold cyan]Step {n}/{total}[/]  [white]{title}[/]",
        style="cyan"
    ))
    con.print()


def ok(msg: str):
    con.print(f"  [bold green]✓[/]  {msg}")


def err(msg: str):
    con.print(f"  [bold red]✗[/]  [red]{msg}[/]")


def info(msg: str):
    con.print(f"  [dim]ℹ[/]  [dim]{msg}[/]")


def ask(prompt: str, default: str = "",
        password: bool = False) -> str:
    if password:
        return getpass.getpass(f"  {prompt}: ").strip()
    display = (
        f"  [bold]{prompt}[/]"
        + (f" [dim](default: {default})[/]" if default else "")
    )
    return Prompt.ask(display, default=default, console=con).strip()


def confirm(prompt: str, default: bool = True) -> bool:
    return Confirm.ask(
        f"  [bold]{prompt}[/]",
        default=default,
        console=con
    )


def verify_aws(ak: str, sk: str,
               region: str) -> tuple[bool, str]:
    with Live(
        Spinner("dots", text=" [dim]Contacting AWS...[/]"),
        console=con, transient=True
    ):
        try:
            result = subprocess.run(
                ["aws", "sts", "get-caller-identity",
                 "--query", "Account", "--output", "text"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ,
                     "AWS_ACCESS_KEY_ID"    : ak,
                     "AWS_SECRET_ACCESS_KEY": sk,
                     "AWS_DEFAULT_REGION"   : region}
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip()[:200]
        except subprocess.TimeoutExpired:
            return False, "Connection timed out (15s)"
        except FileNotFoundError:
            return False, "AWS CLI not found"
        except Exception as e:
            return False, str(e)
