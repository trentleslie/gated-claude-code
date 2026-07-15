import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUM = re.compile(r"(?<![\w:])\d+\.\d+|(?<![\w:.])\d{2,}")


def scrub(text: str) -> str:
    text = _EMAIL.sub("<redacted>", text)
    text = _NUM.sub("<redacted>", text)
    return text
