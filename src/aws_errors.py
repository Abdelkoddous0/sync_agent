"""Safe descriptions of AWS failures: error codes and clock problems, never messages.

AWS and credential-helper messages can contain credential details, so only the
exception type and AWS's short error code are shown. A wrong PC clock is the most
common cause of "correct keys rejected", so it gets an explicit explanation.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

# AWS rejects requests signed more than 15 minutes away from its clock.
MAX_SKEW_SECONDS = 5 * 60
CLOCK_CODES = {'SignatureDoesNotMatch', 'RequestTimeTooSkewed', 'InvalidSignatureException', 'RequestExpired'}


def error_code(exc):
    response = getattr(exc, 'response', None)
    code = response.get('Error', {}).get('Code') if isinstance(response, dict) else None
    return code if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9.]{1,64}', code) else None


def clock_skew_seconds(exc):
    """PC clock minus AWS clock, from the failed response's Date header; None if unknown."""
    response = getattr(exc, 'response', None)
    try:
        date = response['ResponseMetadata']['HTTPHeaders']['date']
        return (datetime.now(timezone.utc) - parsedate_to_datetime(date)).total_seconds()
    except (TypeError, KeyError, ValueError, IndexError):
        return None


def clock_hint(skew):
    direction = 'behind' if skew < 0 else 'ahead of'
    minutes = round(abs(skew) / 60)
    amount = f'{minutes // 60} h {minutes % 60} min' if minutes >= 60 else f'{minutes} min'
    return (f'This PC clock is {amount} {direction} the real time, so AWS rejects every request. '
            'Turn on Settings > Time & language > Date & time > "Set time automatically", then "Sync now" '
            '(or set the time manually). AWS cannot check the credentials until the clock is right, so if it '
            'still fails afterwards, check the access keys too.')


def measure_clock_skew(region='eu-central-1', timeout=5):
    """PC clock minus AWS clock from an unauthenticated STS request; None if unreachable."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(f'https://sts.{region}.amazonaws.com/', method='HEAD')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = response.headers
    except urllib.error.HTTPError as exc:
        headers = exc.headers
    except (OSError, ValueError):
        return None
    try:
        return (datetime.now(timezone.utc) - parsedate_to_datetime(headers['Date'])).total_seconds()
    except (TypeError, KeyError, ValueError, IndexError):
        return None


def cli_error_code(stderr):
    """AWS CLI prints 'An error occurred (Code) when calling ...'; return just the code."""
    match = re.search(r'An error occurred \(([A-Za-z0-9.]{1,64})\)', stderr or '')
    return match.group(1) if match else None


def describe(exc):
    """'ClientError(SignatureDoesNotMatch)', plus a clock explanation when that is the cause."""
    code = error_code(exc)
    text = type(exc).__name__ + (f'({code})' if code else '')
    skew = clock_skew_seconds(exc)
    if skew is not None and abs(skew) > MAX_SKEW_SECONDS and (code in CLOCK_CODES or code is None):
        text += '. ' + clock_hint(skew)
    return text
