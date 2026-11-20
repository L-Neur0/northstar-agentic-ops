"""Tests for the service's upload composition and its `document_question` log line (spec 14 §3.16 R6).

Why: the upload now ends with the agent's question; operations must see that it was asked (how
many keys, how many wait, from an image or not) without any file name, value or description ever
reaching a log line, because those are the expert's business content.
What: AC-14.89: one `document_question` line per successful upload with the R6 fields, and a
sentinel planted in the file name, a value and the file description appears in no log record.
Must not: reach Azure (`FakeLLM`). Spec 14 §3.16.
"""

from __future__ import annotations

import logging

from app.services.process_discovery.llm import CallType

from .documents.helpers import SITE_STEPS, expert_steps, procedure_profile
from .test_service import OWNER, Harness, company, h, llm  # noqa: F401  (fixtures)

SENTINEL = "QUOKKASENTINEL"
TEXT = f"Site report {SENTINEL}\nSite | Cost centre | Budget | {SENTINEL} variance\n".encode()
REPLY = {
    "document_role": "step_output_example",
    "target_step": 3,
    "target_named_by": "focus",
    "trigger": {"value": f"Month end {SENTINEL}", "quote": f"Site report {SENTINEL}"},
    "file_description": {
        "value": f"Site cost report {SENTINEL} per cost centre",
        "quote": "Site | Cost centre | Budget",
    },
}


async def test_ac_14_89_one_log_line_with_counts_only(h: Harness, company, caplog):  # noqa: F811
    caplog.set_level(logging.INFO, logger="app")
    profile = expert_steps(h.ctx.vocab, procedure_profile(h.ctx.vocab), SITE_STEPS)
    seeded = await h.seed(profile=profile, last_question={"focus": ["process.substeps[3].data"]})
    assert h.llm is not None
    h.llm.add(CallType.READ_DOCUMENT, REPLY)
    session, _report = await h.service.upload_document(
        OWNER, seeded.id, filename=f"{SENTINEL}.txt", data=TEXT, config=company.documents
    )
    [line] = [r for r in caplog.records if r.getMessage() == "document_question"]
    fields = vars(line)
    assert fields["session_id"] == seeded.id and fields["document_id"] == session.documents[0].id
    assert (fields["phase"], fields["keys"], fields["remaining"], fields["from_image"], fields["outcome"]) == (
        session.phase.value,
        2,
        0,
        False,
        "read",
    )
    assert SENTINEL in session.messages[-1].text  # the question shows the value to the expert...
    for record in caplog.records:  # ...but no log line carries it
        assert SENTINEL not in record.getMessage() and SENTINEL not in repr(vars(record))
