"""
Core logic for Redemption Code Buddy
"""

import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


from profiler import logger, timed

DIGITS = string.digits
UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
SYMBOLS = "!@#$%&*?"
AMBIGUOUS = "0O1Il|"


@dataclass
class GenerationConfig:
    count: int = 100
    length: int = 12
    group_size: int = 4
    use_digits: bool = False
    use_upper: bool = True
    use_lower: bool = False
    use_symbols: bool = False
    custom_chars: str = ""
    exclude_chars: str = ""
    exclude_ambiguous: bool = False
    no_repeats: bool = False
    prefix: str = ""
    suffix: str = ""
    separator: str = "-"
    force_upper: bool = False
    force_lower: bool = False

    def validate(self):
        if self.count < 1:
            raise ValueError("'Number of codes' must be at least 1.")
        if self.length < 1:
            raise ValueError("'Random part length' must be at least 1.")
        if self.group_size < 0:
            raise ValueError("'Group size' cannot be negative.")
        if self.force_upper and self.force_lower:
            raise ValueError(
                "Choose either force UPPERCASE or force lowercase, not both."
            )


@dataclass
class GenerationResult:
    codes: list
    charset_size: int
    capacity: int
    attempts: int

    @property
    def duplicates_rejected(self) -> int:
        return self.attempts - len(self.codes)


# ------------------------------------------------- Building Blocks
@timed
def build_charset(config: GenerationConfig) -> str:
    """Returns the sorted, de-duplicated pool of characters to draw from."""
    chars = ""
    if config.use_digits:
        chars += DIGITS
    if config.use_upper:
        chars += UPPER
    if config.use_lower:
        chars += LOWER
    if config.use_symbols:
        chars += SYMBOLS
    chars += config.custom_chars

    remove = set(config.exclude_chars)
    if config.exclude_ambiguous:
        remove.update(AMBIGUOUS)
    return "".join(sorted({c for c in chars if not c.isspace() and c not in remove}))


def random_body(charset: str, length: int, no_repeats: bool = False) -> str:
    """One random string from a cryptographically secure RNG (hot path: not decorated)."""
    if not no_repeats or len(charset) < 2:
        return "".join(secrets.choice(charset) for _ in range(length))
    out = []
    for _ in range(length):
        c = secrets.choice(charset)
        while out and c == out[-1]:
            c = secrets.choice(charset)
        out.append(c)
    return "".join(out)


def format_code(
    body: str, prefix: str, suffix: str, separator: str, group_size: int
) -> str:
    """Apply grouping, prefix and suffix to a random body (hot path: not decorated)."""
    if group_size and group_size > 0:
        glue = separator if separator else "-"
        body = glue.join(
            body[i : i + group_size] for i in range(0, len(body), group_size)
        )
    parts = [p for p in (prefix, body, suffix) if p]
    return (separator or "").join(parts)


# ------------------------------------------------- Main Operations


@timed
def generate_codes(config: GenerationConfig, existing=None) -> GenerationResult:
    config.validate()
    charset = build_charset(config=config)
    if not charset:
        raise ValueError(
            "The character pool is empty. Select at least one character type."
        )

    def finalize(code: str) -> str:
        if config.force_upper:
            return code.upper()
        if config.force_lower:
            return code.lower()
        return code

    folded = config.force_upper or config.force_lower
    effective_pool = len(set(finalize(charset))) if folded else len(charset)
    capacity = effective_pool**config.length
    seen = set(existing or ())

    if config.count > capacity - len(seen):
        raise ValueError(
            f"Not enough unique combinations: pool of {effective_pool} characters x "
            f"length {config.length} allows about {capacity:,} codes. Increase the "
            f"length or widen the character set."
        )

    prefix, suffix = config.prefix.strip(), config.suffix.strip()
    logger.info(
        "Generating %s codes (length=%s, pool=%s chars, group=%s)",
        f"{config.count:,}",
        config.length,
        len(charset),
        config.group_size,
    )

    result = []
    attempts, max_attempts = 0, config.count * 50 + 1000
    while len(result) < config.count and attempts < max_attempts:
        attempts += 1
        code = finalize(
            format_code(
                random_body(charset, config.length, config.no_repeats),
                prefix,
                suffix,
                config.separator,
                config.group_size,
            )
        )
        if code in seen:
            continue
        seen.add(code)
        result.append(code)

    if len(result) < config.count:
        raise ValueError(
            f"Only {len(result):,} unique codes could be generated. "
            f"Try a longer length or a larger character set."
        )

    gen = GenerationResult(result, len(charset), capacity, attempts)
    if gen.duplicates_rejected:
        logger.debug("Rejected %d duplicate candidates", gen.duplicates_rejected)
    return gen


def resolve_output_path(
    folder, filename, add_timestamp=False, default_folder=None, now=None
) -> Path:
    folder = Path((folder or "").strip() or default_folder or ".")
    name = (filename or "").strip() or "codes.txt"
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    if "." not in name:
        name += ".txt"
    if add_timestamp:
        stem, dot, ext = name.rpartition(".")
        name = f"{stem}_{(now or datetime.now()):%Y%m%d_%H%M%S}{dot}{ext}"
    return folder / name


@timed
def load_existing_codes(path) -> set:
    path = Path(path)
    if not path.exists():
        return set()
    try:
        codes = {
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        logger.info("Loaded %s existing codes from %s", f"{len(codes):,}", path)
        return codes
    except OSError:
        logger.exception("Could not read existing codes from %s", path)
        return set()


@timed
def save_codes(path, codes, append=False) -> Path:
    """Write codes one per line. Raises OSError on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if append and path.exists() and path.stat().st_size > 0:
        with open(path, "rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
    mode = "a" if append and path.exists() else "w"
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        if needs_newline:
            f.write("\n")
        f.write("\n".join(codes) + "\n")
    logger.info("Saved %s codes to %s (mode=%s)", f"{len(codes):,}", path, mode)
    return path
