# Prompt samples for review

This folder belongs to the tests of the [AI Use Case Discovery Agent](../../../../README.md) backend. These files show the full messages that each model call of the interview receives (spec 14 §3.9). They were captured
from real turns that ran with the scripted `FakeLLM`, so no live model was called. You regenerate them with
`UPDATE_PROMPT_SAMPLES=1 uv run pytest tests/unit/process_discovery/interview/test_prompt_samples.py`. If a prompt
changes and the samples are not regenerated, a test fails, so the samples always match the code.

| File | Call | Sample state |
|---|---|---|
| `extract_1_context_start.txt` | EXTRACT | 1 · Start: `context` phase, the expert's first answer to the welcome |
| `extract_2_find_cluster_proposal.txt` | EXTRACT | 2 · `find`: name agreed, a cluster proposal put to the expert, posture *narrowed* |
| `extract_3_steps_deferred_and_proposal.txt` | EXTRACT | 3 · `steps`: mid-walk on step 2 of 4, *Time today* deferred, a document proposal waiting on step 2 *Systems* |
| `extract_4_find_steering_question.txt` | EXTRACT | 4 · `find`: the expert names three pieces of recurring work (they become steered candidates, spec 14 §3.15) |
| `extract_5_find_recommendation.txt` | EXTRACT | 5 · `find`: the answer to the last steering question (`candidate_signals`) |
| `extract_6_steps_listed_then_tier_a.txt` | EXTRACT | 6 · `step_count`: the expert lists the four steps in one answer (short step walk, spec 14 §3.19) |
| `classify_1_first_name_both_halves.txt` | CLASSIFY | 1 · A first process name: scope and placement asked together |
| `classify_2_widening_scope_only.txt` | CLASSIFY | 2 · A widening answer: scope re-scored only (cluster already decided) |
| `classify_3_placement_only.txt` | CLASSIFY | 3 · Scope settled for the name, cluster still open: placement only |
| `guide_1_context_start.txt` | GUIDE | 1 · Start: asks for the next context field |
| `guide_2_find_cluster_proposal.txt` | GUIDE | 2 · The cluster proposal with its meaning and the runner-up, the narrowed posture |
| `guide_3_steps_deferred_and_proposal.txt` | GUIDE | 3 · The walk: the document proposal is presented first (it outranks the next cell) |
| `guide_4_find_steering_question.txt` | GUIDE | 4 · The first steering question: how often and how long, for each candidate |
| `guide_5_find_recommendation.txt` | GUIDE | 5 · The recommendation: the STEERING block with the code's why lines, the expert decides |
| `guide_6_steps_listed_then_tier_a.txt` | GUIDE | 6 · The first grouped step question: the six Tier A fields of step 1 in one open question (§3.19) |

CLASSIFY does not run in every state (only when a process name is new or a widening question was answered),
so its three samples show its three variants instead of the six GUIDE / EXTRACT states.

Points to review (wording only; the structure and the rules are held by tests):

1. EXTRACT shows the profile as registry-keyed JSON, GUIDE as prose from `render_profile`
   with proposals marked `(proposed, from <document>)`.
2. The find headline forbids bringing up clusters except when THIS TURN puts one to the expert.
3. The wrap-up (not sampled) offers each given-up field once more with an easy settle (a range, "not sure",
   "none") and the Close button as the honest exit (spec 14 Q4).
