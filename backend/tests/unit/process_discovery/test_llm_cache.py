"""Tests for the model reply cache (spec 11 §3.7).

Why: the cache saves Azure credit in local development and evaluation runs, but it holds model
replies that may quote expert text. It must therefore run only in stage `local`, store only usable
output, never turn a corrupt file into an error, and miss whenever anything that shapes the reply
changes.
What: an `AzureLLM` over a stub SDK client with `LLMCache(tmp_path)`; the tests count requests and
look at the files. Implements spec 11, AC-11.27 to AC-11.29.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from app.services.process_discovery import llm as llm_module
from app.services.process_discovery.json_schema import strict_json_schema
from app.services.process_discovery.llm import CallType, LLMEmptyResponseError, LLMInvalidOutputError, LLMUsage
from app.services.process_discovery.llm_cache import LLMCache
from tests.unit.process_discovery.test_llm_support import (
    completion,
    demo_settings,
    events,
    make_llm,
    make_settings,
    messages,
    no_text_in_logs,  # noqa: F401  (autouse fixture)
    one_call_line,
)


class Answer(BaseModel):
    answer: str


class OtherAnswer(BaseModel):
    answer: str
    why: str


def cached_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def local(tmp_path: Path, **values: Any):
    return make_settings(llm_cache_enabled=True, llm_cache_dir=tmp_path, **values)


async def test_a_repeated_call_is_served_from_the_cache(tmp_path, caplog):
    """AC-11.27: no request, no usage, `outcome=cache_hit`."""
    seen: list[LLMUsage] = []
    llm, create, _ = make_llm(
        [completion("first"), completion("second")], local(tmp_path), cache=LLMCache(tmp_path), usage_hook=seen.append
    )
    assert await llm.generate_text(CallType.GUIDE, messages()) == "first"
    caplog.clear()
    assert await llm.generate_text(CallType.GUIDE, messages()) == "first"
    assert create.await_count == 1
    assert len(seen) == 1
    line = one_call_line(caplog)
    assert line["outcome"] == "cache_hit" and line["level"] == "INFO"
    assert line["attempts"] == 0 and line["total_tokens"] == 0


async def test_structured_and_json_hits_are_parsed(tmp_path):
    """AC-11.27: a hit goes through the same parsing as a fresh reply."""
    llm, create, _ = make_llm(
        [completion('{"answer": "a"}'), completion('{"P01": "x"}')], local(tmp_path), cache=LLMCache(tmp_path)
    )
    for _ in range(2):
        assert (await llm.generate_structured(Answer, CallType.MAP, messages())).answer == "a"
        assert await llm.generate_json(CallType.EXTRACT, messages()) == {"P01": "x"}
    assert create.await_count == 2


async def test_the_cache_file_layout(tmp_path):
    """§3.7 rule 3: `<dir>/<call_type>/<key[:2]>/<key>.json` holding text and created."""
    llm, _, _ = make_llm([completion("hello")], local(tmp_path), cache=LLMCache(tmp_path))
    await llm.generate_text(CallType.GUIDE, messages())
    [path] = cached_files(tmp_path)
    key = LLMCache.key("app-chat", CallType.GUIDE, messages(), "text")
    assert path == tmp_path / "GUIDE" / key[:2] / f"{key}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["text"] == "hello" and "created" in data


def test_the_key_changes_with_every_input():
    """AC-11.27: a change to any message, the schema, the deployment or the call type is a miss."""
    base = LLMCache.key("app-chat", CallType.GUIDE, messages(), "text")
    assert base == LLMCache.key("app-chat", CallType.GUIDE, messages(), "text")
    assert len(base) == 64
    changed_message = messages()
    changed_message[1]["content"] = str(changed_message[1]["content"]) + "!"
    variants = [
        LLMCache.key("app-chat", CallType.GUIDE, changed_message, "text"),
        LLMCache.key("app-chat", CallType.GUIDE, messages()[:1], "text"),
        LLMCache.key("other-chat", CallType.GUIDE, messages(), "text"),
        LLMCache.key("app-chat", CallType.EXTRACT, messages(), "text"),
        LLMCache.key("app-chat", CallType.GUIDE, messages(), "json_object"),
        LLMCache.key("app-chat", CallType.GUIDE, messages(), strict_json_schema(Answer, "Answer")),
        LLMCache.key("app-chat", CallType.GUIDE, messages(), strict_json_schema(OtherAnswer, "Answer")),
    ]
    assert len({base, *variants}) == len(variants) + 1


async def test_a_changed_schema_is_a_miss(tmp_path):
    """AC-11.27, through the client."""
    llm, create, _ = make_llm(
        [completion('{"answer": "a"}'), completion('{"answer": "b", "why": "c"}')],
        local(tmp_path),
        cache=LLMCache(tmp_path),
    )
    await llm.generate_structured(Answer, CallType.MAP, messages())
    result = await llm.generate_structured(OtherAnswer, CallType.MAP, messages())
    assert result.why == "c" and create.await_count == 2


async def test_demo_never_reads_or_writes_the_cache(tmp_path):
    """AC-11.28: a true setting is ignored outside `local`."""
    settings = demo_settings(llm_cache_enabled=True, llm_cache_dir=tmp_path)
    llm, create, _ = make_llm([completion("one"), completion("two")], settings, cache=LLMCache(tmp_path))
    assert await llm.generate_text(CallType.GUIDE, messages()) == "one"
    assert await llm.generate_text(CallType.GUIDE, messages()) == "two"
    assert create.await_count == 2
    assert cached_files(tmp_path) == []


def test_create_llm_ignores_the_cache_in_demo_and_says_so(monkeypatch, tmp_path, caplog):
    """AC-11.28: logged once as a warning at start-up."""
    for name in (
        "AsyncAzureOpenAI",
        "ManagedIdentityCredential",
        "DefaultAzureCredential",
        "get_bearer_token_provider",
    ):
        monkeypatch.setattr(llm_module, name, MagicMock())
    llm = llm_module.create_llm(demo_settings(llm_cache_enabled=True, llm_cache_dir=tmp_path))
    assert llm._cache is None
    assert len(events(caplog, "llm_cache_ignored")) == 1


def test_create_llm_turns_the_cache_on_in_local(monkeypatch, tmp_path):
    """§3.7 rule 1."""
    for name in ("AsyncAzureOpenAI", "DefaultAzureCredential", "get_bearer_token_provider"):
        monkeypatch.setattr(llm_module, name, MagicMock())
    on = llm_module.create_llm(make_settings(llm_cache_enabled=True, llm_cache_dir=tmp_path))
    off = llm_module.create_llm(make_settings(llm_cache_enabled=False, llm_cache_dir=tmp_path))
    assert isinstance(on._cache, LLMCache) and off._cache is None


@pytest.mark.parametrize(
    "responses",
    [
        [completion("cut", finish_reason="length")],
        [completion(None)],
    ],
    ids=["truncated", "empty"],
)
async def test_errors_are_never_cached(tmp_path, responses):
    """AC-11.29."""
    llm, _, _ = make_llm(responses, local(tmp_path), cache=LLMCache(tmp_path))
    with pytest.raises(LLMEmptyResponseError):
        await llm.generate_text(CallType.GUIDE, messages())
    assert cached_files(tmp_path) == []


async def test_invalid_output_is_never_cached(tmp_path):
    """AC-11.29."""
    llm, _, _ = make_llm([completion("[]"), completion("nope")], local(tmp_path), cache=LLMCache(tmp_path))
    with pytest.raises(LLMInvalidOutputError):
        await llm.generate_structured(Answer, CallType.MAP, messages())
    assert cached_files(tmp_path) == []


async def test_only_the_valid_retry_reply_is_cached(tmp_path):
    """AC-11.29: after an invalid then a valid reply, the hit is the valid one."""
    llm, create, _ = make_llm(
        [completion("nope"), completion('{"answer": "good"}')], local(tmp_path), cache=LLMCache(tmp_path)
    )
    await llm.generate_structured(Answer, CallType.MAP, messages())
    assert (await llm.generate_structured(Answer, CallType.MAP, messages())).answer == "good"
    assert create.await_count == 2


@pytest.mark.parametrize("garbage", ["{not json", '{"no_text": 1}', '{"text": ""}', '["x"]'])
async def test_a_corrupt_file_is_a_miss_and_is_overwritten(tmp_path, caplog, garbage):
    """AC-11.29: logged by key only, then replaced by the next valid result."""
    key = LLMCache.key("app-chat", CallType.GUIDE, messages(), "text")
    path = tmp_path / "GUIDE" / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text(garbage, encoding="utf-8")
    llm, create, _ = make_llm([completion("fresh")], local(tmp_path), cache=LLMCache(tmp_path))
    assert await llm.generate_text(CallType.GUIDE, messages()) == "fresh"
    assert create.await_count == 1
    [corrupt] = events(caplog, "llm_cache_corrupt")
    assert corrupt.__dict__["key"] == key
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == "fresh"


def test_put_leaves_no_temporary_files(tmp_path):
    """§3.7 rule 3: write to a temporary file, then an atomic rename."""
    cache = LLMCache(tmp_path)
    key = LLMCache.key("app-chat", CallType.GUIDE, messages(), "text")
    cache.put(CallType.GUIDE, key, "one")
    cache.put(CallType.GUIDE, key, "two")
    assert cache.get(CallType.GUIDE, key) == "two"
    assert len(cached_files(tmp_path)) == 1


def test_a_missing_entry_is_none(tmp_path):
    assert LLMCache(tmp_path).get(CallType.GUIDE, "0" * 64) is None


@pytest.mark.parametrize("key", ["../../etc/passwd", "abc", "Z" * 64])
def test_a_malformed_key_is_refused(tmp_path, key):
    """A key is always a SHA-256 hex digest, so it can never name a path outside the cache."""
    with pytest.raises(ValueError):
        LLMCache(tmp_path).put(CallType.GUIDE, key, "x")
