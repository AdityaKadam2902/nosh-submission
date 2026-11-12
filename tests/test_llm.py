import json

import pytest
from pydantic import BaseModel

from recipebot.llm import LLM, LLMBadOutput, LLMUnavailable, GeminiBackend


class S(BaseModel):
    x: int


class HTTPErr(Exception):
    def __init__(self, code):
        super().__init__(f"http {code}")
        self.code = code


def mk(tmp_path, replies, **kw):
    calls = []

    def backend(model, prompt, system, schema, timeout):
        calls.append(prompt)
        r = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    sleeps = []
    return LLM(model="m", backend=backend, cache_dir=tmp_path / "c", sleep=sleeps.append, jitter=False, **{"base_delay": 1.0, **kw}), calls, sleeps


def test_json_parsed_and_cached(tmp_path):
    llm, calls, _ = mk(tmp_path, ['{"x": 1}'])
    assert llm.generate_json("p", S).x == 1 and llm.generate_json("p", S).x == 1
    assert len(calls) == 1 and llm.cache_hits == 1


def test_cache_persists_across_instances_and_keys_on_prompt(tmp_path):
    a, calls_a, _ = mk(tmp_path, ['{"x": 1}'])
    a.generate_json("p", S)
    b, calls_b, _ = mk(tmp_path, ['{"x": 2}'])
    assert b.generate_json("p", S).x == 1 and not calls_b
    assert b.generate_json("other", S).x == 2


def test_retries_429_with_exponential_backoff_then_succeeds(tmp_path):
    llm, calls, sleeps = mk(tmp_path, [HTTPErr(429), HTTPErr(503), '{"x": 3}'])
    assert llm.generate_json("p", S).x == 3
    assert len(calls) == 3 and sleeps == [1.0, 2.0] and llm.retries == 2


def test_gives_up_after_max_retries(tmp_path):
    llm, calls, _ = mk(tmp_path, [HTTPErr(429)], max_retries=2)
    with pytest.raises(LLMUnavailable):
        llm.generate_json("p", S)
    assert len(calls) == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_non_retryable_errors_fail_fast(tmp_path, code):
    llm, calls, sleeps = mk(tmp_path, [HTTPErr(code)])
    with pytest.raises(LLMUnavailable) as e:
        llm.generate_json("p", S)
    assert len(calls) == 1 and not sleeps and str(code) in str(e.value)


def test_timeout_is_retried(tmp_path):
    llm, calls, _ = mk(tmp_path, [TimeoutError("slow"), '{"x": 4}'])
    assert llm.generate_json("p", S).x == 4 and len(calls) == 2


def test_invalid_json_gets_one_reask_and_is_not_cached(tmp_path):
    llm, calls, _ = mk(tmp_path, ["not json", '{"x": 5}'])
    assert llm.generate_json("p", S).x == 5 and len(calls) == 2 and "ONLY the JSON" in calls[1]


def test_invalid_json_twice_raises_bad_output_and_nothing_cached(tmp_path):
    llm, calls, _ = mk(tmp_path, ["nope"])
    with pytest.raises(LLMBadOutput):
        llm.generate_json("p", S)
    assert len(calls) == 2 and not list((tmp_path / "c").glob("*.json")) if (tmp_path / "c").exists() else True


def test_code_fences_stripped(tmp_path):
    llm, _, _ = mk(tmp_path, ['```json\n{"x": 6}\n```'])
    assert llm.generate_json("p", S).x == 6


def test_request_budget(tmp_path):
    llm, _, _ = mk(tmp_path, ['{"x": 1}'], max_calls=1)
    llm.generate_json("a", S)
    with pytest.raises(LLMUnavailable):
        llm.generate_json("b", S)


def test_text_generation_cached(tmp_path):
    llm, calls, _ = mk(tmp_path, ["hello"])
    assert llm.generate_text("p") == "hello" and llm.generate_text("p") == "hello" and len(calls) == 1


def test_missing_key_or_model_means_unavailable_not_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        LLM(model="m", backend=GeminiBackend(api_key=None), cache_dir=None).generate_text("p")
    with pytest.raises(LLMUnavailable):
        LLM(model=None, backend=lambda *a: "x", cache_dir=None).generate_text("p")


def test_fallback_model_used_after_primary_exhausts_retryable_errors(tmp_path):
    seen = []

    def backend(model, prompt, system, schema, timeout):
        seen.append(model)
        if model == "primary":
            raise HTTPErr(503)
        return '{"x": 9}'

    llm = LLM(model="primary", fallback_model="backup", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=1)
    assert llm.generate_json("p", S).x == 9 and seen == ["primary", "primary", "backup"] and llm.fallbacks_used == 1


def test_no_fallback_on_non_retryable_error_and_last_error_recorded(tmp_path):
    llm = LLM(model="primary", fallback_model="backup", backend=lambda *a: (_ for _ in ()).throw(HTTPErr(404)), cache_dir=None, sleep=lambda s: None)
    with pytest.raises(LLMUnavailable):
        llm.generate_text("p")
    assert llm.fallbacks_used == 0 and "404" in llm.last_error and "primary" in llm.last_error


def test_pacing_sleeps_between_calls(tmp_path):
    sleeps = []
    llm = LLM(model="m", backend=lambda *a: "ok", cache_dir=None, sleep=sleeps.append, min_interval=5.0)
    llm.generate_text("a")
    llm.generate_text("b")
    assert sleeps and 0 < sleeps[0] <= 5.0


def test_primary_gives_up_fast_when_fallback_exists(tmp_path):
    seen = []

    def backend(model, prompt, system, schema, timeout):
        seen.append(model)
        if model == "primary":
            raise HTTPErr(429)
        return "ok"

    llm = LLM(model="primary", fallback_model="backup", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=5)
    assert llm.generate_text("p") == "ok" and seen == ["primary", "primary", "backup"]
