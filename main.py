"""
Redemption Code Buddy

Easily generate redemption codes personalized to your needs. Developed with Flet by Salman Zaheer.

"""

import re
import secrets
import string
from datetime import datetime
from pathlib import Path

import flet as ft

DIGITS = string.digits
UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
SYMBOLS = "!@#$%&*?"
AMBIGUOUS = "0O1Il|"

PREVIEW_LIMIT = 420

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def build_charset(
    use_digits,
    use_upper,
    use_lower,
    user_symbols,
    custom_chars,
    exclude_ambiguous,
    exclude_custom,
):
    """Return the sorted, de-duplicated pool of characters to draw from."""
    chars = ""

    if use_digits:
        chars += DIGITS
    if use_upper:
        chars += UPPER
    if use_lower:
        chars += LOWER
    if user_symbols:
        chars += SYMBOLS
    chars += custom_chars

    remove = set()
    if exclude_ambiguous:
        remove.update(AMBIGUOUS)
    remove.update(exclude_custom)

    # remove whitespace, duplicates and excludes characters
    pool = {c for c in chars if not c.isspace() and c not in remove}
    return "".join(sorted(pool))


def random_body(charset, length, no_repeats):
    """Generate one random string using a cryptographically secure RNG."""
    if not no_repeats or len(charset) < 2:
        return "".join(secrets.choice(charset) for _ in range(length))
    out = []
    for _ in range(length):
        c = secrets.choice(charset)
        while out and c == out[-1]:
            c = secrets.choice(charset)
        out.append(c)
    return "".join(out)


def format_code(body, prefix, suffix, separator, group_size):
    """Apply filters to a random body."""
    if group_size and group_size > 0:
        glue = separator if separator else "-"
        body = glue.join(
            body[i : i + group_size] for i in range(0, len(body), group_size)
        )
    parts = [p for p in (prefix, body, suffix) if p]
    join_with = separator if separator else ""
    return join_with.join(parts)
