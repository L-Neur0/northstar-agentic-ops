"""The one READ_DOCUMENT model call for every non-BPMN upload (spec 17 §3.7).

Why: reading a procedure, a spreadsheet or an example report needs a model, but a failed reading
must not fail the upload or the interview: the document is kept as a record with no proposals, and
the expert can remove it and try again. Only a spent daily budget and a cancelled request stop the
upload, because the service must answer those differently (429, or nothing at all).
What: `read_with_model(llm, name, text, profile, vocab=..., documents=...)` builds the messages
(`prompts.py`) and calls `generate_structured` with the registry-generated model (`schema.py`);
the client owns the token budget, timeouts, retries and the one invalid-output retry (spec 11).
Returns the raw reading, or `None` when the model failed.
Must not: call the SDK directly, log the text or the reply, or swallow `LLMBudgetExceededError` or
`asyncio.CancelledError`. Spec 17 §3.7; AC-17.33.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from ..domain.field_spec import Vocabulary
from ..llm import LLM, CallType, LLMEmptyResponseError, LLMInvalidOutputError, LLMUnavailableError
from .prompts import read_document_messages
from .schema import read_document_model


async def read_with_model(
    llm: LLM,
    name: str,
    text: str,
    profile: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> BaseModel | None:
    """The model's reading of the document, or `None` on an empty, invalid or unavailable reply."""
    messages = read_document_messages(name, text, profile, vocab=vocab, documents=documents)
    try:
        return await llm.generate_structured(read_document_model(), CallType.READ_DOCUMENT, messages)
    except (LLMEmptyResponseError, LLMInvalidOutputError, LLMUnavailableError):
        return None
