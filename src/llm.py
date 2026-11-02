import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

ROLES = {
    "large": ("MODEL_LARGE", "llama-3.3-70b-versatile"),
    "fast": ("MODEL_FAST", "llama-3.1-8b-instant"),
}
_overrides: dict = {}


class LLMConfigError(RuntimeError):
    pass


@lru_cache(maxsize=64)
def _build(role: str, temperature: float) -> ChatGroq:
    if not os.getenv("GROQ_API_KEY"):
        raise LLMConfigError("GROQ_API_KEY is not set. Copy .env.example to .env and fill it in.")
    env_name, default = ROLES[role]
    return ChatGroq(
        model=os.getenv(env_name, default),
        temperature=temperature,
        timeout=float(os.getenv("LLM_TIMEOUT_S", "30")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )


def get_model(role: str, temperature: float = 0.0):
    if role in _overrides:
        return _overrides[role]
    if role not in ROLES:
        raise LLMConfigError(f"Unknown model role {role!r}. Known: {list(ROLES)}")
    return _build(role, temperature)


def get_large(temperature: float = 0.0):
    return get_model("large", temperature)


def get_fast(temperature: float = 0.0):
    return get_model("fast", temperature)


def override(role: str, model) -> None:
    _overrides[role] = model


def reset() -> None:
    _overrides.clear()
    _build.cache_clear()
