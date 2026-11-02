import datetime as dt
from typing import Optional

FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y")


def to_iso(value) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    for fmt in FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"{value!r} is not a recognised date; use YYYY-MM-DD")