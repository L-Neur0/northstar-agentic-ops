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
`asyncio.CancelledError`. Spec 17 §3.7; AC-17.33. Amendment: the reading context goes into the
messages (§3.18), and `read_image_with_model` sends one image with the image output model (§3.19
item 4; AC-17.56).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from ..domain.field_spec import Vocabulary
from ..llm import LLM, CallType, LLMEmptyResponseError, LLMInvalidOutputError, LLMUnavailableError
from .context import ReadingContext
from .image import PreparedImage
from .prompts import read_document_messages, read_image_messages
from .schema import read_document_model, read_image_model


async def read_with_model(
    llm: LLM,
    name: str,
    text: str,
    profile: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
    context: ReadingContext | None = None,
) -> BaseModel | None:
    """The model's reading of the document, or `None` on an empty, invalid or unavailable reply."""
    messages = read_document_messages(name, text, profile, vocab=vocab, documents=documents, context=context)
    try:
        return await llm.generate_structured(read_document_model(), CallType.READ_DOCUMENT, messages)
    except (LLMEmptyResponseError, LLMInvalidOutputError, LLMUnavailableError):
        return None


async def read_image_with_model(
    llm: LLM,
    name: str,
    image: PreparedImage,
    profile: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
    context: ReadingContext | None = None,
) -> BaseModel | None:
    """The model's reading of one image (transcription, summary, proposals), or `None` when the model failed."""
    messages = read_image_messages(name, image, profile, vocab=vocab, documents=documents, context=context)
    try:
        return await llm.generate_structured(read_image_model(), CallType.READ_DOCUMENT, messages)
    except (LLMEmptyResponseError, LLMInvalidOutputError, LLMUnavailableError):
        return None
