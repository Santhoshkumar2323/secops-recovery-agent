import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.json"


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ResourcePolicy:
    name: str
    hot_days: int
    restorable: bool
    glacier_days: Optional[int]
    dr_alternative: str
    aliases: tuple = ()


def _non_negative(name: str, key: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyError(f"{name}.{key} must be a non-negative integer, got {value!r}")
    return value


def _parse(name: str, raw) -> ResourcePolicy:
    if not isinstance(raw, dict):
        raise PolicyError(f"{name} must be an object")
    glacier = raw.get("glacier_days")
    if glacier is not None:
        glacier = _non_negative(name, "glacier_days", glacier)
    restorable = raw.get("restorable", True)
    if not isinstance(restorable, bool):
        raise PolicyError(f"{name}.restorable must be true or false")
    alt = raw.get("dr_alternative")
    if not isinstance(alt, str) or not alt.strip():
        raise PolicyError(f"{name}.dr_alternative must be a non-empty string")
        
    raw_aliases = raw.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raise PolicyError(f"{name}.aliases must be a list of strings")
    if not all(isinstance(a, str) for a in raw_aliases):
        raise PolicyError(f"All items in {name}.aliases must be strings")
        
    return ResourcePolicy(
        name=name,
        hot_days=_non_negative(name, "hot_days", raw.get("hot_days")),
        restorable=restorable,
        glacier_days=glacier,
        dr_alternative=alt.strip(),
        aliases=tuple(raw_aliases),
    )


@lru_cache(maxsize=1)
def load_policy() -> dict:
    path = Path(os.getenv("SECOPS_POLICY_PATH", str(DEFAULT_PATH)))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PolicyError(f"Cannot read policy file {path}: {e}") from e
    resources = data.get("resources") if isinstance(data, dict) else None
    if not resources:
        raise PolicyError(f"Policy file {path} defines no resources")
    return {name: _parse(name, raw) for name, raw in resources.items()}


def reload() -> None:
    load_policy.cache_clear()


def resource_names() -> list:
    return list(load_policy())


def get(resource: str) -> ResourcePolicy:
    try:
        return load_policy()[resource]
    except KeyError:
        raise PolicyError(f"Unknown resource {resource!r}. Known: {resource_names()}") from None


def glacier_status(resource: str, days_old: int) -> tuple:
    limit = get(resource).glacier_days
    if limit is None:
        return False, 0
    left = limit - days_old
    return left >= 0, left


def alias_hints() -> str:
    return "; ".join(
        f"{', '.join(p.aliases)} -> {p.name}" for p in load_policy().values() if p.aliases
    )
