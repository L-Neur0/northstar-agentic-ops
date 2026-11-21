"""Tests for conflicts in the turn (spec 14 §3.17 items 1, 5, 6): asked by code, chosen, closed, or left.

Why: a conflict is asked with exact words and no GUIDE call, a clear choice is the answer (EXTRACT's
writes to the same field are dropped), the expert's own words close it, two unclear replies leave
the stored value as it is, and a "yes" to a proposal group can never confirm a value under dispute.
What: AC-14.92, AC-14.93, AC-14.97 to AC-14.100 through the real turn (`run_turn` over the graph)
with scripted EXTRACT replies, `document_question`, `confirm_proposals` and the report gaps.
Must not: call a real model. Spec 14 §3.17.
"""

from __future__ import annotations

import logging

from app.models.process_discovery_schemas import LastQuestion
from app.services.process_discovery.artifacts.report import build_report
from app.services.process_discovery.interview.doc_question import document_question
from app.services.process_discovery.interview.phases import proposal_group
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.conflicts import open_conflicts
from app.services.process_discovery.profile.proposals import (
    ConflictOffer,
    FieldProposal,
    ProposalDiff,
    confirm_proposals,
)
from app.services.process_discovery.profile.shapes import meta_for, stored_value

from .conflict_helpers import (
    DATA,
    DESCRIPTION,
    EFFORT,
    FREQUENCY_KEY,
    OUTPUTS_KEY,
    SYSTEMS,
    example_session,
    site_offer,
    slides_offer,
)
from .helpers import NOW, fake, turn


def meta_of(profile, key):
    """The meta entry, which these tests expect to exist."""
    meta = meta_for(profile, key)
    assert meta is not None
    return meta


def asked(session, keys):
    return session.model_copy(update={"last_question": LastQuestion(conflicts=list(keys))})


def profile_of(session):
    return session.profile.model_dump(by_alias=True)


async def test_ac_14_92_upload_with_proposals_and_a_conflict(ctx):
    goal = FieldProposal("process.substeps[3].goal", "Every variance is explained", "explained")
    systems = FieldProposal("process.substeps[3].systems", ["Excel"], "Excel")
    diff = ProposalDiff("d2", step_cells=(goal, systems), conflicts=site_offer().conflicts)
    session = example_session(ctx, diff)
    question = document_question(
        session,
        document_id="d2",
        name="site_report_march.xlsx",
        from_image=False,
        role="step_output_example",
        target_step=3,
        outcome="read",
        extras=(),
        report_sentence="I read it.",
        ctx=ctx,
    )
    lines = question.text.split("\n")
    assert lines[-2] == "It also differs from what you told me in 1 place; I'll ask about that next."
    assert lines[-1] == "Should I fill it like this, or is something wrong?"
    assert DATA not in question.keys
    session = session.model_copy(update={"last_question": question.last_question})
    llm = fake(EXTRACT=[{}])
    result = await turn(session, "yes", llm, ctx)
    assert result.session.last_question.conflicts == [OUTPUTS_KEY]
    assert result.reply.startswith('About step 3 "Collect explanations" – Data in and out, Outputs:')
    assert llm.calls_of(CallType.GUIDE) == []


def test_ac_14_93_a_disputed_unit_is_never_in_a_proposal_group(ctx):
    session = example_session(ctx, slides_offer())
    profile = profile_of(session)
    group = proposal_group(profile, "steps", {}, vocab=ctx.vocab)
    assert EFFORT not in group and SYSTEMS in group
    closed = confirm_proposals(profile, [EFFORT], vocab=ctx.vocab, at=NOW).profile
    assert open_conflicts(closed) == []


async def test_ac_14_97_choices(ctx):
    session = asked(example_session(ctx, site_offer()), [OUTPUTS_KEY])
    both = await turn(session, "both", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    profile = profile_of(both.session)
    assert stored_value(profile, DATA)["outputs"] == ["a cost report", DESCRIPTION]
    parts = meta_of(profile, DATA)["parts"]
    assert [(p["item"], p["documentId"]) for p in parts] == [("a cost report", None), (DESCRIPTION, "d2")]
    assert open_conflicts(profile) == []
    offered = await turn(session, "2", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    profile = profile_of(offered.session)
    assert stored_value(profile, DATA)["outputs"] == [DESCRIPTION]
    assert meta_of(profile, DATA)["status"] == "confirmed"
    mine = await turn(session, "mine", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    profile = profile_of(mine.session)
    before = profile_of(session)
    assert stored_value(profile, DATA) == stored_value(before, DATA)
    assert meta_of(profile, DATA) == meta_of(before, DATA)
    assert stored_value(profile, EFFORT) == stored_value(before, EFFORT)
    assert open_conflicts(profile) == []


async def test_ac_14_98_choice_drops_extract_and_own_words_close(ctx):
    session = asked(example_session(ctx, site_offer()), [OUTPUTS_KEY])
    dropped = await turn(session, "both", fake(EXTRACT=[{DATA: {"outputs": ["Other"]}}], GUIDE=["Next?"]), ctx)
    assert "Other" not in stored_value(profile_of(dropped.session), DATA)["outputs"]
    words = {DATA: {"outputs": ["The Excel report, one tab per site"]}}
    own = await turn(session, "It's the Excel report, one tab per site", fake(EXTRACT=[words], GUIDE=["Next?"]), ctx)
    profile = profile_of(own.session)
    assert stored_value(profile, DATA)["outputs"] == ["The Excel report, one tab per site"]
    assert meta_of(profile, DATA)["source"] == "expert"
    assert open_conflicts(profile) == []
    nothing = await turn(session, "ok", fake(EXTRACT=[{}]), ctx)
    assert [c.conflict_key for c in open_conflicts(profile_of(nothing.session))] == [OUTPUTS_KEY]


async def test_ac_14_99_two_unclear_replies_leave_it(ctx, nig_config):
    session = asked(example_session(ctx, site_offer()), [OUTPUTS_KEY])
    first = await turn(session, "ok", fake(EXTRACT=[{}]), ctx)
    assert first.session.counters.conflict_asks == {OUTPUTS_KEY: 1}
    assert first.session.last_question.conflicts == [OUTPUTS_KEY]
    second = await turn(first.session, "ok", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    profile = profile_of(second.session)
    [view] = open_conflicts(profile)
    assert view.status == "left"
    assert second.session.last_question.conflicts == []
    assert stored_value(profile, DATA)["outputs"] == ["a cost report"]
    report = build_report(second.session, nig_config.organisation, ctx.vocab, nig_config.solutions)
    assert (  # spec 27: the gaps are the last line of part 6
        'Not settled: the expert says "a cost report"; "site_report_march.xlsx" says "' + DESCRIPTION + '"'
    ) in report.feasibility.gaps


async def test_ac_14_100_tick_closes_a_document_conflict_and_the_log(ctx, caplog):
    session = example_session(ctx, slides_offer())
    closed = confirm_proposals(profile_of(session), [EFFORT], vocab=ctx.vocab, at=NOW).profile
    assert stored_value(closed, EFFORT)["frequency"] == "monthly" and open_conflicts(closed) == []
    caplog.set_level(logging.INFO)
    sentinel = "SENTINEL-weekly-SENTINEL"
    planted = ProposalDiff("d3", conflicts=(ConflictOffer(EFFORT, "frequency", sentinel, "q"),))
    session = asked(example_session(ctx, planted), [FREQUENCY_KEY])
    await turn(session, "ok", fake(EXTRACT=[{}]), ctx)
    [line] = [r for r in caplog.records if r.getMessage() == "interview_turn"]
    assert (line.__dict__["ask_kind"], line.__dict__["choice"], line.__dict__["left"]) == ("conflict", "none", 0)
    for record in caplog.records:
        assert sentinel not in str(record.__dict__) and "review_slides" not in str(record.__dict__)
