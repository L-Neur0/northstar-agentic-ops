"""Tests for the EXTRACT and CLASSIFY prompts: structure and required rules (spec 14 §3.9; AC-14.3, AC-14.58, AC-14.60).

Why: the prompts are drafts pending review, so the tests hold their structure and the rules spec 14
requires (checked by phrase), never their exact wording. What: fences, keys, the step bound, the
"JSON" word on every EXTRACT request, the frame rule, the value test, codes not names, and the
calibration rows as the scorer grades them.
"""

import pytest

from app.services.process_discovery.domain.field_spec import PHASE_ORDER, extract_keys
from app.services.process_discovery.domain.scope import CALIBRATION
from app.services.process_discovery.interview.prompts.classifier import classifier_system, classifier_user
from app.services.process_discovery.interview.prompts.extractor import extractor_system, extractor_user
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, cost_review_profile
from .helpers import fake, new_session, turn


def test_the_extract_prompt_structure(ctx):
    """AC-14.3, AC-14.58."""
    system = extractor_system(
        empty_profile(), "Which department are you in?", {"focus": ["department"]}, vocab=ctx.vocab, phase="context"
    )
    assert system.startswith("You are a data extraction assistant.")
    for key in extract_keys():
        assert f'"{key}"' in system
    assert '"process.cluster"' not in system
    assert "<<<PROFILE" in system and "<<<PREVIOUS_QUESTION" in system
    assert "It was about these keys: department" in system
    assert "Do NOT infer" in system
    assert "When in doubt, copy it verbatim" in system
    assert '[{"none": true}]' in system and '"none_identified": true' in system
    assert "never write the cluster, a confirmation or a flag" in system
    assert "candidates" not in system
    assert "candidates" in extractor_system(empty_profile(), "", {}, vocab=ctx.vocab, phase="find")
    assert "__meta" not in system
    assert extractor_user("hi") == "<<<EXPERT_MESSAGE\nhi\nEXPERT_MESSAGE>>>"


def test_the_step_bound(ctx):
    """AC-14.58."""
    unknown = extractor_system(empty_profile(), "", {}, vocab=ctx.vocab, phase="step_count")
    assert "at most 6" in unknown and "process.substep_count" in unknown
    known = extractor_system(
        cost_review_profile(ctx.vocab, steps=4, filled_steps=1), "", {}, vocab=ctx.vocab, phase="steps"
    )
    assert "runs from 1 to 4" in known and "step under discussion is step 2" in known


@pytest.mark.parametrize("phase", PHASE_ORDER)
async def test_every_extract_request_says_json(ctx, phase):
    """AC-14.60."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    await turn(new_session(ctx, phase=phase), "something", llm, ctx)
    for call in llm.calls:
        if call.method == "json":
            assert any("JSON" in m["content"] for m in call.messages)


@pytest.mark.parametrize(("scope", "placement"), [(True, True), (True, False), (False, True)])
def test_the_classify_prompt_structure(ctx, scope, placement):
    """AC-14.58."""
    system = classifier_system(with_scope=scope, with_placement=placement, taxonomy=ctx.vocab.taxonomy)
    assert "JSON" in system
    assert "Judge ONLY the activity exactly as" in system
    if scope:
        assert "R1. `multi_role`" in system and "R5. `external_consumer`" in system
        assert "not a colleague who merely sees it" in system
        for activity, _signals, expected in CALIBRATION:
            line = next(line for line in system.splitlines() if f'"{activity}"' in line)
            assert line.endswith(f"→ {expected}")
    else:
        assert "already decided: do not return it" in system and "R1." not in system
    if placement:
        assert "Answer with the CODE, never the cluster name" in system
        assert ctx.vocab.taxonomy.prompt_block() in system
        assert '"UNKNOWN"' in system
    else:
        assert "FIN ·" not in system


def test_classify_neither_half_is_a_bug(ctx):
    with pytest.raises(ValueError):
        classifier_system(with_scope=False, with_placement=False, taxonomy=ctx.vocab.taxonomy)


def test_the_classify_user_message_carries_little(ctx):
    """AC-14.58: department, role and the fenced activity, never the whole profile."""
    profile = cost_review_profile(ctx.vocab, steps=2)
    user = classifier_user("Monthly cost review", profile)
    assert "Department: Finance" in user and "Role: Cost controller" in user
    assert "<<<ACTIVITY\nMonthly cost review\nACTIVITY>>>" in user
    assert "Head of Controlling" not in user
    assert "Re-score" in classifier_user("x", profile, widening=True)
    p = apply_changes(empty_profile(), {"department": "IT"}, vocab=ctx.vocab, at=AT).profile
    assert "Role: (none)" in classifier_user("x", p)


def test_extract_names_the_steered_candidates_in_find(ctx):
    """AC-14.66 (live check): the model must reuse the candidate names, so they are listed, fenced."""
    names = ["monthly cost review", "chase site managers"]
    system = extractor_system(empty_profile(), "", {}, vocab=ctx.vocab, phase="find", candidates=names)
    assert "candidate_signals" in system
    block = system.rsplit("<<<CANDIDATES", 1)[1].split("CANDIDATES>>>", 1)[0]
    assert all(n in block for n in names)
    assert "<<<CANDIDATES" not in extractor_system(empty_profile(), "", {}, vocab=ctx.vocab, phase="find")
