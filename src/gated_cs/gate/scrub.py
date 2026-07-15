import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUM = re.compile(r"(?<![\w:])\d+\.\d+|(?<![\w:.])\d{2,}")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def _redact_quoted(m):
    q = m.group(0)[0]          # preserve the quote character
    return f"{q}<redacted>{q}"


def scrub(text: str) -> str:
    """Redact data values from error/traceback text before it returns to the model.

    Redacts: quoted-string contents (single/double), email addresses, and numeric
    literals (decimals and 2+ digit integers). Preserves: exception type names and
    file:line references (e.g. ``file.py:12``). This is defense-in-depth for the gate's
    error path, not a complete DLP filter.
    """
    text = _QUOTED.sub(_redact_quoted, text)
    text = _EMAIL.sub("<redacted>", text)
    text = _NUM.sub("<redacted>", text)
    return text
