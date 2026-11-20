"""Tests for the agent's question after an upload, built by code (spec 14 §3.16).

Why: right after an upload the agent names the file, says exactly what it would fill and asks
whether that is right, so the expert can answer in the chat. The question is built by code (no
model call), carries the group in `last_question.proposals` (so the existing yes / no reading works),
marks every value read from an image, and falls back to the report sentence when there is nothing
to ask. A later yes confirms the document's group and nothing else, also in `context` and over an
armed cluster proposal.
What: AC-14.81 and AC-14.83 to AC-14.87, on sessions built with the real writers; the turn tests
run the real graph with `FakeLLM`.
Must not: reach Azure. Spec 14 §3.16.
"""

from __future__ import annotations

from typing import Any, Literal

from app.models.process_discovery_schemas import Message, MessageRole, Profile, Session
from app.services.process_discovery.domain.scope import keyword_placement
from app.services.process_discovery.interview.doc_question import document_question
from app.services.process_discovery.interview.nodes import fallback_question
from app.services.process_discovery.interview.prompts.guide import guide_system, missing_line
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.scoring import finish_check
from tests.unit.process_discovery.documents.helpers import SITE_STEPS, expert_steps, procedure_profile

from ..profile.builders import AT
from .helpers import fake, new_session, turn
from .test_replies_cluster import cluster_session

DATA3 = "process.substeps[3].data"
DESCRIPTION = "Excel cost report per site with variance comments, one tab per site"
HEADER = "Site | Cost centre | Budget | Actual | Variance | Comment"
EXAMPLE_1 = (
    'From "site_report_march.xlsx" I\'d fill:\n'
    '- Step 3 "Collect explanations" – Outputs: ' + DESCRIPTION + "\n"
    "Should I fill it like this, or is something wrong?"
)


def applied(ctx, profile: dict[str, Any], diff: ProposalDiff, **update: Any) -> Session:
    written = apply_proposals(profile, diff, vocab=ctx.vocab, at=AT).profile
    update.setdefault("scope", {"verdict": None, "scoped_for": "Monthly cost review"})
    update.setdefault("placement", {"proposal": None, "placed_for": "Monthly cost review"})
    return new_session(ctx, profile=Profile.model_validate(written), **update)


def ask(
    ctx,
    session: Session,
    *,
    document_id="d2",
    name="site_report_march.xlsx",
    role="step_output_example",
    target: int | None = 3,
    outcome: Literal["read", "failed"] = "read",
    extras=(),
    image=False,
    sentence="I read it.",
):
    return document_question(
        session,
        document_id=document_id,
        name=name,
        from_image=image,
        role=role,
        target_step=target,
        outcome=outcome,
        extras=extras,
        report_sentence=sentence,
        ctx=ctx,
    )


def site(ctx, **update: Any) -> Session:
    profile = expert_steps(ctx.vocab, procedure_profile(ctx.vocab), SITE_STEPS)
    diff = ProposalDiff("d2", step_cells=(FieldProposal(DATA3, {"inputs": [], "outputs": [DESCRIPTION]}, HEADER),))
    return applied(ctx, profile, diff, phase="steps", **update)


def uploaded(session: Session, question) -> Session:
    """What the service saves: the question appended as an agent message, its group as the last question."""
    update: dict[str, Any] = {
        "messages": [*session.messages, Message(role=MessageRole.AGENT, text=question.text, at=AT)]
    }
    if question.last_question is not None:
        update["last_question"] = question.last_question
    return session.model_copy(update=update)


# --- AC-14.81 -----------------------------------------------------------------------------------------


def test_ac_14_81_worked_example_4(ctx):
    question = ask(ctx, site(ctx))
    assert question.text == EXAMPLE_1
    assert question.last_question is not None
    assert (question.last_question.proposals, question.last_question.focus) == ([DATA3], [])
    assert question.remaining == 0


# --- AC-14.83 the group ---------------------------------------------------------------------------------


FIELDS = (
    FieldProposal("process.trigger", "Month-end close", "month-end close"),
    FieldProposal("process.end_result", "The cost report", "the cost report"),
    FieldProposal("process.business_pain", "Chasing", "chasing"),
)


def mixed(ctx, counters=None) -> Session:
    profile = expert_steps(ctx.vocab, procedure_profile(ctx.vocab), SITE_STEPS)
    cells = (
        FieldProposal("process.substeps[3].systems", ["Excel"], "Excel"),
        FieldProposal(DATA3, {"inputs": [], "outputs": ["Report"]}, "Report"),
        FieldProposal("process.substeps[1].goal", "Get the numbers", "numbers"),
    )
    profile = apply_proposals(profile, ProposalDiff("d1", fields=(FIELDS[0],)), vocab=ctx.vocab, at=AT).profile
    session = applied(ctx, profile, ProposalDiff("d2", fields=FIELDS[1:], step_cells=cells), phase="steps")
    return session.model_copy(update={"counters": session.counters.model_copy(update=counters or {})})


def test_ac_14_83_step_scoped_group(ctx):
    question = ask(ctx, mixed(ctx))
    assert question.keys == ("process.substeps[3].systems", DATA3, "process.end_result", "process.business_pain")
    assert question.remaining == 1  # step 1's goal, later
    assert "process.trigger" not in question.keys  # another document's proposal


def test_ac_14_83_whole_process_group_and_deferred_and_given_up(ctx):
    question = ask(ctx, mixed(ctx), role="whole_process", target=None)
    assert question.keys == ("process.end_result", "process.business_pain")
    deferred = mixed(ctx, {"field_asks": {"process.end_result": 3}})
    assert "process.end_result" in ask(ctx, deferred, role="whole_process", target=None).keys
    given_up = mixed(ctx, {"field_asks": {"process.end_result": 5}})
    assert "process.end_result" not in ask(ctx, given_up, role="whole_process", target=None).keys


def test_ac_14_83_a_skipped_cell_is_left_out(ctx):
    session = mixed(ctx)
    profile = session.profile.model_dump(by_alias=True)
    profile["process"]["substeps"][2]["__skipped"] = ["systems"]
    session = session.model_copy(update={"profile": Profile.model_validate(profile)})
    assert "process.substeps[3].systems" not in ask(ctx, session).keys


# --- AC-14.84 the message ----------------------------------------------------------------------------------


def test_ac_14_84_message_lines(ctx):
    profile = expert_steps(ctx.vocab, procedure_profile(ctx.vocab), SITE_STEPS)
    long = "x" * 300
    cells = (
        FieldProposal(DATA3, {"inputs": ["Ledger export", "Budget file"], "outputs": ["Cost report"]}, "q"),
        FieldProposal("process.substeps[3].goal", long, "q"),
    )
    session = applied(ctx, profile, ProposalDiff("d2", fields=(FIELDS[0],), step_cells=cells), phase="steps")
    question = ask(ctx, session, extras=("It is long, so I read only the first part.",))
    lines = question.text.split("\n")
    assert '- Step 3 "Collect explanations" – Inputs: Ledger export; Budget file' in lines
    assert '- Step 3 "Collect explanations" – Outputs: Cost report' in lines
    assert "- Trigger: Month-end close" in lines
    assert lines[-2] == "It is long, so I read only the first part."
    assert lines[-1] == "Should I fill it like this, or is something wrong?"
    goal = next(line for line in lines if "Goal" in line)
    assert goal.endswith("…") and len(goal.split(": ", 1)[1]) == 200
    for word in ("noted", "saved", "recorded"):
        assert word not in question.text.lower()


def test_ac_14_84_step_names_and_more_values(ctx):
    from app.services.process_discovery.profile.proposals import StepProposal

    names = ("Export actuals", "Compare", "Collect", "Review", "Send")
    steps = tuple(StepProposal((FieldProposal("name", n, n), FieldProposal("goal", f"{n} goal", n))) for n in names)
    session = applied(ctx, procedure_profile(ctx.vocab), ProposalDiff("d1", steps=steps), phase="boundaries")
    question = ask(ctx, session, document_id="d1", role="whole_process", target=None)
    assert "- The steps: 1 Export actuals · 2 Compare · 3 Collect · 4 Review · 5 Send" in question.text
    assert "There is more in it (5 other values); I'll ask about those next." in question.text


# --- AC-14.85 images -------------------------------------------------------------------------------------


def image_session(ctx) -> Session:
    from app.models.process_discovery_schemas import DocumentRecord

    profile = expert_steps(ctx.vocab, procedure_profile(ctx.vocab), SITE_STEPS)
    diff = ProposalDiff(
        "d3", step_cells=(FieldProposal("process.substeps[2].systems", ["Planning tool"], "Planning tool"),)
    )
    record = DocumentRecord(
        id="d3", name="planning_tool.png", kind="png", bytes=10, chars=5, text="Image", uploaded_at=AT, outcome="read"
    )
    return applied(ctx, profile, diff, phase="steps", documents=[record.model_dump(by_alias=True)])


def test_ac_14_85_image_marks_everywhere(ctx):
    session = image_session(ctx)
    question = ask(ctx, session, document_id="d3", name="planning_tool.png", role="step_material", target=2, image=True)
    assert question.text.split("\n")[1] == '- Step 2 "Compare with budget" – Systems: Planning tool (from an image)'
    state = {
        "profile": session.profile.model_dump(by_alias=True),
        "phase": "steps",
        "documents": [{"id": "d3", "name": "planning_tool.png", "kind": "png"}],
    }
    keys = ("process.substeps[2].systems",)
    profile = session.profile.model_dump(by_alias=True)
    system = guide_system(state, Ask("proposals", keys), finish_check(profile, vocab=ctx.vocab), vocab=ctx.vocab)
    assert "(from planning_tool.png) (from an image)" in system
    line = missing_line(
        profile, keys[0], vocab=ctx.vocab, documents={"d3": "planning_tool.png"}, images=frozenset({"d3"})
    )
    assert "proposed from planning_tool.png (from an image)" in line
    text = fallback_question(
        Ask("proposals", keys), profile, vocab=ctx.vocab, process_name="x", images=frozenset({"d3"})
    )
    assert text.startswith("I saw this in your image: ")


# --- AC-14.86 nothing to ask ------------------------------------------------------------------------------


def test_ac_14_86_nothing_kept_or_failed(ctx):
    session = new_session(ctx)
    nothing = ask(ctx, session, sentence='I read "a.txt" but found nothing new for the form.')
    assert nothing.text == 'I read "a.txt" but found nothing new for the form. Let\'s carry on where we left off.'
    assert nothing.last_question is None and nothing.keys == ()
    failed = ask(ctx, site(ctx), outcome="failed", sentence="I couldn't read this document just now.")
    assert failed.text.endswith("Let's carry on where we left off.") and failed.last_question is None


# --- AC-14.82, AC-14.87 the reply -------------------------------------------------------------------------


async def test_ac_14_82_yes_no_correction_and_other(ctx):
    session = uploaded(site(ctx), ask(ctx, site(ctx)))
    yes = await turn(session, "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    rows = yes.session.profile.process.substeps
    assert rows[2].meta["data"].status == "confirmed"
    no = await turn(session, "no", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert no.session.profile.process.substeps[2].data.outputs == []
    corrected = await turn(
        session,
        "It's a PDF, not Excel",
        fake(EXTRACT=[{DATA3: {"outputs": ["PDF cost report per site"]}}], GUIDE=["Q?"]),
        ctx,
    )
    cell = corrected.session.profile.process.substeps[2]
    assert cell.data.outputs == ["PDF cost report per site"] and cell.meta["data"].source == "expert"
    other = await turn(session, "ok", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert other.session.profile.process.substeps[2].meta["data"].status == "proposed"
    assert other.session.counters.cell_asks.get(DATA3) == 1


async def test_ac_14_87_in_context_and_over_an_armed_cluster(ctx):
    profile = apply_changes(procedure_profile(ctx.vocab), {}, vocab=ctx.vocab, at=AT).profile
    start = applied(ctx, profile, ProposalDiff("d1", fields=(FIELDS[0],)), phase="context")
    session = uploaded(start, ask(ctx, start, document_id="d1", role="whole_process", target=None))
    result = await turn(session, "yes", fake(EXTRACT=[{}], CLASSIFY=[], GUIDE=["Q?"]), ctx)
    assert result.session.profile.meta["process.trigger"].status == "confirmed"

    armed = cluster_session(ctx)
    p = apply_proposals(
        armed.profile.model_dump(by_alias=True), ProposalDiff("d1", fields=(FIELDS[0],)), vocab=ctx.vocab, at=AT
    ).profile
    armed = armed.model_copy(update={"profile": Profile.model_validate(p)})
    before = armed.counters.field_asks.get("process.cluster", 0)
    after_upload = uploaded(armed, ask(ctx, armed, document_id="d1", role="whole_process", target=None))
    result = await turn(after_upload, "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert result.session.profile.meta["process.trigger"].status == "confirmed"
    assert not result.session.profile.process.cluster.code
    assert result.session.counters.field_asks.get("process.cluster", 0) == before
    assert (
        result.session.placement.proposal is not None
        and result.session.placement.proposal.code == keyword_placement("FIN")["code"]
    )
