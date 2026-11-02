import pytest

from src import llm


@pytest.fixture(autouse=True)
def clean_llm_cache():
    llm.reset()
    yield
    llm.reset()


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError, match="GROQ_API_KEY"):
        llm.get_large()


def test_override_replaces_the_model():
    fake = object()
    llm.override("large", fake)
    assert llm.get_large() is fake


def test_timeout_and_retries_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_S", "7")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    model = llm.get_fast()
    assert model.request_timeout == 7
    assert model.max_retries == 1