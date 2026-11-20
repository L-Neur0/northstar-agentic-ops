"""Session builders for the conflict tests: worked example 5 of spec 17 §3.21, built with the real writers.

Why: the conflict question, the reply reading and the turn must be tested on the exact state an
upload leaves (the `__conflicts` sidecar written by `apply_proposals`), never on a hand-typed dict.
What: `DATA`, `EFFORT`, the file names, `example_session` (expert outputs "a cost report"; d1 proposed
step 4 effort and systems; optional conflict diffs applied) and `site_offer`/`slides_offer`.
Must not: patch a writer or call a model. Spec 14 §3.17, spec 17 §3.21 item 7.
"""

from __future__ import annotations

from typing import Any

from app.models.process_discovery_schemas import DocumentRecord, Profile, Session
from app.services.process_discovery.interview.types import InterviewContext
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import (
    ConflictOffer,
    FieldProposal,
    ProposalDiff,
    apply_proposals,
)
from tests.unit.process_discovery.documents.helpers import SITE_STEPS, expert_steps, procedure_profile

from .helpers import NOW, new_session

DATA = "process.substeps[3].data"
EFFORT = "process.substeps[4].effort"
SYSTEMS = "process.substeps[4].systems"
OUTPUTS_KEY = "process.substeps[3].data.outputs"
FREQUENCY_KEY = "process.substeps[4].effort.frequency"
PROCEDURE = "Monthly cost review procedure.docx"
SITE = "site_report_march.xlsx"
SLIDES = "review_slides.pptx"
DESCRIPTION = "Excel cost report per site with variance comments, one tab per site"
HEADER = "Site | Cost centre | Budget | Actual | Variance | Comment"


def record(document_id: str, name: str, kind: Any = "docx") -> dict[str, Any]:
    return DocumentRecord(
        id=document_id, name=name, kind=kind, bytes=10, chars=4, text="text", uploaded_at=NOW, outcome="read"
    ).model_dump(by_alias=True)


def site_offer() -> ProposalDiff:
    return ProposalDiff("d2", conflicts=(ConflictOffer(DATA, "outputs", [DESCRIPTION], HEADER),))


def slides_offer() -> ProposalDiff:
    return ProposalDiff("d3", conflicts=(ConflictOffer(EFFORT, "frequency", "weekly", "weekly"),))


def example_profile(ctx: InterviewContext) -> dict[str, Any]:
    vocab = ctx.vocab
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    profile = apply_changes(profile, {DATA: {"outputs": ["a cost report"]}}, vocab=vocab, at=NOW).profile
    d1 = ProposalDiff(
        "d1",
        step_cells=(
            FieldProposal(EFFORT, {"duration": "2 hours", "frequency": "monthly"}, "takes 2 hours every month"),
            FieldProposal(SYSTEMS, ["Ledger system"], "in the ledger system"),
        ),
    )
    return apply_proposals(profile, d1, vocab=vocab, at=NOW).profile


def example_session(ctx: InterviewContext, *diffs: ProposalDiff, profile: dict[str, Any] | None = None) -> Session:
    """Phase `steps`, the 5 rows of the monthly cost review, the three files, and `diffs` applied."""
    current = profile if profile is not None else example_profile(ctx)
    for diff in diffs:
        current = apply_proposals(current, diff, vocab=ctx.vocab, at=NOW).profile
    return new_session(
        ctx,
        profile=Profile.model_validate(current),
        phase="steps",
        scope={"verdict": None, "scoped_for": "Monthly cost review"},
        placement={"proposal": None, "placed_for": "Monthly cost review"},
        documents=[record("d1", PROCEDURE), record("d2", SITE, "xlsx"), record("d3", SLIDES, "pptx")],
    )
