"""Tests for the conflict question (spec 14 §3.17 items 1–3): when it is asked, the group, and the exact words.

Why: the expert must see both values, both sources and only the choices that make sense, in words
a test can hold; the upload of a conflicting file must ask about it at once, without a model call.
What: AC-14.91 (the upload reply of example 4, through the service's upload steps), AC-14.94 (the
group) and AC-14.95 (examples 5 and 6, "both" only when it fits, the image mark, the 200-character cut).
Must not: call a real model. Spec 14 §3.17.
"""

from __future__ import annotations

from pathlib import Path

from app.models.process_discovery_schemas import LastQuestion
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview.conflict_question import conflict_question
from app.services.process_discovery.interview.phases import conflict_group, next_ask
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import ConflictOffer, ProposalDiff
from app.services.process_discovery.service import upload_into
from tests.unit.process_discovery.documents.helpers import site_reply

from .conflict_helpers import (
    DATA,
    EFFORT,
    OUTPUTS_KEY,
    example_profile,
    example_session,
    site_offer,
    slides_offer,
)
from .helpers import NOW

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "documents"
EXAMPLE_4 = (
    'About step 3 "Collect explanations" – Data in and out, Outputs:\n'
    'You said "a cost report". "site_report_march.xlsx" says '
    '"Excel cost report per site with variance comments, one tab per site".\n'
    "Which should I keep: yours, the document's, both, or tell me in your words?"
)
EXAMPLE_5 = (
    'About step 4 "Review" – Effort, frequency:\n'
    '"Monthly cost review procedure.docx" says "monthly"; "review_slides.pptx" says "weekly".\n'
    "Which is right, or how would you put it?"
)


def names(session):
    return {d.id: d.name for d in session.documents}


def profile_of(session):
    return session.profile.model_dump(by_alias=True)


async def test_ac_14_91_upload_reply_is_example_4(ctx, nig_config):
    session = example_session(ctx)
    session = session.model_copy(
        update={
            "documents": [d for d in session.documents if d.id != "d2"],
            "last_question": LastQuestion(focus=[DATA]),  # the walk is on step 3's data
        }
    )
    llm = FakeLLM({CallType.READ_DOCUMENT: [site_reply()]})
    new, report = await upload_into(
        session,
        filename="site_report_march.xlsx",
        data=(FIXTURES / "site_report_march.xlsx").read_bytes(),
        llm=llm,
        config=nig_config.documents,
        ctx=ctx,
        now=NOW,
    )
    assert report.conflicts == 1
    assert new.messages[-1].text == EXAMPLE_4
    assert new.last_question.conflicts == [OUTPUTS_KEY]
    assert new.last_question.proposals == []
    assert [c.call_type for c in llm.calls] == [CallType.READ_DOCUMENT]  # no GUIDE: the question is code


def test_ac_14_94_the_group(ctx):
    profile = example_profile(ctx)
    offers = tuple(
        ConflictOffer(f"process.substeps[4].{leaf}", sub, value, "q")
        for leaf, sub, value in (
            ("goal", None, "Other goal"),
            ("owner", None, "Head of finance"),
            ("handover", None, "By mail"),
            ("pain_points", None, ["Late"]),
        )
    )
    profile = apply_changes(
        profile,
        {
            "process.substeps[4].goal": "Variances explained",
            "process.substeps[4].owner": "Controller",
            "process.substeps[4].handover": "In a meeting",
            "process.substeps[4].pain_points": ["Chasing"],
        },
        vocab=ctx.vocab,
        at=NOW,
    ).profile
    session = example_session(ctx, ProposalDiff("d3", conflicts=offers), profile=profile)
    group = conflict_group(profile_of(session))
    assert len(group) == 3 and all(v.key.startswith("process.substeps[4]") for v in group)
    mixed = example_session(ctx, site_offer(), slides_offer())
    first = conflict_group(profile_of(mixed))
    assert [v.conflict_key for v in first] == [OUTPUTS_KEY]  # step 3 and step 4, two files, two kinds: apart


def test_ac_14_95_example_5_and_example_6(ctx):
    session = example_session(ctx, slides_offer())
    group = conflict_group(profile_of(session))
    assert conflict_question(profile_of(session), group, vocab=ctx.vocab, names=names(session)) == EXAMPLE_5
    profile = apply_changes(
        example_profile(ctx),
        {"process.substeps[4].owner": "the controller", EFFORT: {"duration": "2 hours", "frequency": "monthly"}},
        vocab=ctx.vocab,
        at=NOW,
    ).profile
    offers = ProposalDiff(
        "d3",
        conflicts=(
            ConflictOffer("process.substeps[4].owner", None, "Head of finance", "q"),
            ConflictOffer(EFFORT, "frequency", "weekly", "q"),
        ),
    )
    grouped = example_session(ctx, offers, profile=profile)
    text = conflict_question(
        profile_of(grouped), conflict_group(profile_of(grouped)), vocab=ctx.vocab, names=names(grouped)
    )
    assert text == (
        'About step 4 "Review", "review_slides.pptx" differs from what you told me:\n'
        '- Step owner: you said "the controller"; the document says "Head of finance".\n'
        '- Effort, frequency: you said "monthly"; the document says "weekly".\n'
        "Which should I keep: yours or the document's, or tell me in your words?"
    )


def test_ac_14_95_both_only_when_it_fits_image_mark_and_cut(ctx):
    profile = apply_changes(
        example_profile(ctx), {"process.substeps[2].activities": ["a", "b", "c", "d"]}, vocab=ctx.vocab, at=NOW
    ).profile
    offer = ProposalDiff("d2", conflicts=(ConflictOffer("process.substeps[2].activities", None, ["e", "f"], "q"),))
    session = example_session(ctx, offer, profile=profile)
    text = conflict_question(
        profile_of(session), conflict_group(profile_of(session)), vocab=ctx.vocab, names=names(session)
    )
    assert text.endswith("Which should I keep: yours or the document's, or tell me in your words?")
    long = "x" * 300
    image = ProposalDiff("d2", conflicts=(ConflictOffer(DATA, "outputs", [long], "q"),), from_image=True)
    session = example_session(ctx, image)
    text = conflict_question(
        profile_of(session), conflict_group(profile_of(session)), vocab=ctx.vocab, names=names(session)
    )
    assert '"site_report_march.xlsx" (from an image) says' in text
    assert ("x" * 199 + "…") in text and ("x" * 200) not in text
    assert text.count("(from an image)") == 1


def test_ac_14_92_conflict_ask_before_proposals(ctx):
    session = example_session(ctx, site_offer())
    state = {
        "profile": profile_of(session),
        "phase": "steps",
        "counters": {},
        "scope": {},
    }
    ask = next_ask(state, vocab=ctx.vocab)
    assert (ask.kind, ask.keys) == ("conflict", (OUTPUTS_KEY,))
