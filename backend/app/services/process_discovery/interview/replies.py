"""Reading a short reply in code, so a gate never hangs on one model token (spec 14 §3.7; product F-02, F-04.5, F-07, F-10).

Why: whether a plain "yes" confirmed the proposed cluster, the document values named in the last
question, or the roles and systems lists, is fully decidable from the state: what was proposed,
what the last question was about, what the last agent message said. Leaving it to the model made
sessions loop ("yes" three times, nothing confirmed). So code reads it, with the configured yes/no
words of every language (union), and the model is never asked what the expert meant.
What: `Lexicon` (from `language.yaml`), `normalise_reply`, `mentions` (whole-word, look-arounds),
`cluster_armed` / `read_cluster_reply`, `recommendation_armed` / `read_recommendation_reply` (§3.15
item 9), `read_proposal_reply`, `read_rollup_reply`, and the
message readers `last_agent_message` / `recent_agent_messages`.
Rules it protects: "ok", "okay", "sure" and "fine" are never a yes (the config loader rejects
them); a reply longer than 6 words decides nothing unless its opening clause is a yes word and the
rest holds no no word (and, for the cluster, names no other cluster): "Yes, that cluster fits." is a
yes, "well yes, but" is not; a correction in the same message outranks a yes.
Must not: write the profile (the extract node applies what these return), call a model, or read a
clock. Spec 14 §3.7, §3.15 item 9; AC-14.6 to AC-14.19, AC-14.72. Amendment §3.17 item 4:
`read_conflict_reply` reads keep / mine / the document / both / 1–3 / a file name; anything else is
the expert's own words (AC-14.96).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

from app.core.config import LanguageConfig

from ..domain.field_spec import Vocabulary
from ..domain.scope import proposable_code
from ..profile.constants import FLAG_SUBSTEPS_COMPLETE, ROLLUP_FLAGS, ROLLUP_KEYS, ROLLUP_TARGETS
from ..profile.shapes import as_list, as_mapping, process_of
from ..profile.verdicts import field_counts

REPLY_MAX_WORDS = 6
CUE_LOOKBACK = 2
#: Where the opening clause of a reply ends: a sentence or clause mark, or a spaced dash.
_CLAUSE_END = re.compile(r"[.,;:!?\u2013\u2014]|\s-\s")
AGENT, EXPERT = "agent", "expert"


def normalise_reply(text: str | None) -> str:
    """Lower case; apostrophes deleted (`that's` → `thats`); other punctuation → space; whitespace collapsed."""
    lowered = re.sub(r"['’ʼ]", "", (text or "").lower())
    lowered = re.sub(r"[^\w\s]+", " ", lowered)
    return " ".join(lowered.split())


def mentions(haystack: str | None, needle: str | None) -> bool:
    """Whether `needle` occurs in `haystack` as a whole word (case-insensitive): `IT` is not inside "with"."""
    word = (needle or "").strip()
    if not word:
        return False
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", haystack or "", re.IGNORECASE) is not None


def opening_clause(text: str | None) -> tuple[str, str]:
    """The reply's opening clause and the rest, both normalised ("Yes, that fits." → ("yes", "that fits"))."""
    parts = _CLAUSE_END.split(text or "", maxsplit=1)
    return normalise_reply(parts[0]), normalise_reply(parts[1] if len(parts) > 1 else "")


@dataclass(frozen=True)
class Lexicon:
    """The union of every configured language's yes, no and cue words, normalised like a reply."""

    yes: frozenset[str]
    no: frozenset[str]
    roles_cues: tuple[str, ...]
    systems_cues: tuple[str, ...]

    @classmethod
    def from_config(cls, language: LanguageConfig) -> Lexicon:
        words = list(language.languages.values())
        return cls(
            yes=frozenset(normalise_reply(w) for lang in words for w in lang.yes),
            no=frozenset(normalise_reply(w) for lang in words for w in lang.no),
            roles_cues=tuple(dict.fromkeys(normalise_reply(w) for lang in words for w in lang.roles_cues)),
            systems_cues=tuple(dict.fromkeys(normalise_reply(w) for lang in words for w in lang.systems_cues)),
        )

    def short(self, text: str | None) -> str:
        """The normalised reply when it is short (≤ 6 words, not empty), else ""."""
        reply = normalise_reply(text)
        return reply if reply and len(reply.split()) <= REPLY_MAX_WORDS else ""

    def is_yes(self, text: str | None) -> bool:
        """A short reply equal to a yes word, or a reply whose opening clause is one and whose rest says no no word."""
        if self.short(text) in self.yes:
            return True
        head, rest = opening_clause(text)
        return bool(rest) and head in self.yes and not any(mentions(rest, w) for w in self.no)

    def is_no(self, text: str | None) -> bool:
        return self.short(text) in self.no


# --- Reading the conversation ------------------------------------------------------------------------


def _messages(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [m for m in (as_mapping(x) for x in (as_list(state.get("messages")) or [])) if m is not None]


def recent_agent_messages(state: Mapping[str, Any], limit: int) -> list[str]:
    """The last `limit` non-empty agent messages, most recent first."""
    out: list[str] = []
    for message in reversed(_messages(state)):
        text = message.get("text")
        if message.get("role") == AGENT and isinstance(text, str) and text.strip():
            out.append(text.strip())
            if len(out) >= limit:
                break
    return out


def last_agent_message(state: Mapping[str, Any]) -> str:
    """The most recent agent message (the question being answered), or ""."""
    found = recent_agent_messages(state, 1)
    return found[0] if found else ""


def last_expert_message(state: Mapping[str, Any]) -> str:
    """The most recent expert message, or ""."""
    for message in reversed(_messages(state)):
        text = message.get("text")
        if message.get("role") == EXPERT and isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _last_question(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return as_mapping(state.get("last_question")) or {}


def _str_list(value: Any) -> list[str]:
    return [v for v in (as_list(value) or []) if isinstance(v, str)]


# --- Cluster ------------------------------------------------------------------------------------------


class ClusterReply(NamedTuple):
    """What a reply decided about the cluster: `(True, "named", code)`, `(True|False, "lexicon", …)` or nothing."""

    verdict: bool | None
    source: Literal["named", "lexicon", "none"]
    code: str | None


NO_CLUSTER_REPLY = ClusterReply(None, "none", None)


def _cluster_open(state: Mapping[str, Any], vocab: Vocabulary) -> bool:
    profile = as_mapping(state.get("profile")) or {}
    return not field_counts(profile, "process.cluster", vocab=vocab)


def cluster_armed(state: Mapping[str, Any], *, vocab: Vocabulary) -> str | None:
    """The code of a live, unanswered cluster proposal, or `None`.

    All of: a proposable code; not rejected; P05 does not count; the last question recorded
    `confirm == "cluster"`; and the last agent message names the cluster or its code as a whole word.
    """
    placement = as_mapping(state.get("placement")) or {}
    code = proposable_code(as_mapping(placement.get("proposal")))
    if not code or placement.get("rejected") is True or not _cluster_open(state, vocab):
        return None
    if _last_question(state).get("confirm") != "cluster":
        return None
    asked = last_agent_message(state)
    cluster = vocab.taxonomy.by_code(code)
    named = mentions(asked, code) or (cluster is not None and mentions(asked, cluster.name))
    return code if named else None


def _names_another_cluster(text: str | None, code: str, vocab: Vocabulary) -> bool:
    """Whether the reply names a cluster other than `code` (its name in any case, or its code in capitals)."""
    return any(
        mentions(text, c.name) or re.search(rf"(?<!\w){re.escape(c.code)}(?!\w)", text or "") is not None
        for c in vocab.taxonomy.clusters
        if c.code != code
    )


def read_cluster_reply(
    state: Mapping[str, Any], text: str | None, *, vocab: Vocabulary, lexicon: Lexicon
) -> ClusterReply:
    """Read a reply to the cluster question in code (§3.7 table): named, short yes, short no, or nothing."""
    question = _last_question(state)
    about_cluster = question.get("confirm") == "cluster" or "process.cluster" in _str_list(question.get("focus"))
    if about_cluster and _cluster_open(state, vocab):
        named = vocab.taxonomy.by_spoken(text)
        if named is not None:
            return ClusterReply(True, "named", named.code)
    armed = cluster_armed(state, vocab=vocab)
    if armed is None:
        return NO_CLUSTER_REPLY
    if lexicon.is_yes(text) and not _names_another_cluster(text, armed, vocab):
        return ClusterReply(True, "lexicon", armed)
    if lexicon.is_no(text):
        return ClusterReply(False, "lexicon", None)
    return NO_CLUSTER_REPLY


# --- The steering recommendation (§3.15 item 9) -------------------------------------------------------------


def recommendation_armed(state: Mapping[str, Any], *, vocab: Vocabulary) -> str | None:
    """The id of the recommended candidate the last question put to the expert, while P04 does not count."""
    steering = as_mapping(state.get("steering")) or {}
    recommended = steering.get("recommended_id")
    profile = as_mapping(state.get("profile")) or {}
    if _last_question(state).get("confirm") != "recommendation" or not isinstance(recommended, str) or not recommended:
        return None
    return None if field_counts(profile, "process.name", vocab=vocab) else recommended


def read_recommendation_reply(
    state: Mapping[str, Any], text: str | None, *, vocab: Vocabulary, lexicon: Lexicon
) -> tuple[Literal["yes", "no"] | None, str | None]:
    """A yes or a short no to an armed recommendation, with the candidate id; anything else decides nothing."""
    armed = recommendation_armed(state, vocab=vocab)
    if armed is None:
        return None, None
    if lexicon.is_yes(text):
        return "yes", armed
    if lexicon.is_no(text):
        return "no", armed
    return None, None


# --- Proposals ----------------------------------------------------------------------------------------


def read_proposal_reply(
    state: Mapping[str, Any], text: str | None, *, lexicon: Lexicon
) -> tuple[Literal["yes", "no"] | None, tuple[str, ...]]:
    """A short yes or no to the proposals named in the last question; anything else decides nothing."""
    keys = tuple(_str_list(_last_question(state).get("proposals")))
    if not keys:
        return None, ()
    if lexicon.is_yes(text):
        return "yes", keys
    if lexicon.is_no(text):
        return "no", keys
    return None, ()


# --- Roll-up lists --------------------------------------------------------------------------------------


def read_rollup_reply(
    state: Mapping[str, Any],
    text: str | None,
    *,
    lexicon: Lexicon,
    steps_written: bool,
    profile_after: Mapping[str, Any],
) -> tuple[str, ...]:
    """The lists a short yes confirms (`"roles"`, `"systems"`), or `()`.

    Only when the incoming phase is `confirm`, the reply is a short yes, no step cell was written
    this turn (an edit outranks the yes) and the walk is still closed. Targets: the roll-up keys of
    the last question; else the cue words of the last 2 agent messages; else the first pending list.
    """
    if state.get("phase") != "confirm" or steps_written or not lexicon.is_yes(text):
        return ()
    proc = process_of(profile_after)
    if proc.get(FLAG_SUBSTEPS_COMPLETE) is not True:
        return ()
    pending = [t for t in ROLLUP_TARGETS if proc.get(ROLLUP_FLAGS[t]) is not True]
    if not pending:
        return ()
    focus = _str_list(_last_question(state).get("focus"))
    asked = tuple(t for t in pending if ROLLUP_KEYS[t] in focus)
    if asked:
        return asked
    cues = {"roles": lexicon.roles_cues, "systems": lexicon.systems_cues}
    recent = recent_agent_messages(state, CUE_LOOKBACK)
    cued = tuple(t for t in pending if any(mentions(m, cue) for m in recent for cue in cues[t]))
    return cued or (pending[0],)


# --- Conflicts (§3.17 item 4) ---------------------------------------------------------------------

#: The reply words of §3.17 item 4 (English and German), normalised like a reply. Kept in code for
#: now; spec 14 §3.17 asks for them in `language.yaml` (a spec 10 change, listed as a deviation).
CONFLICT_KEEP = frozenset({"keep", "keep it", "leave it", "as it is", "behalten"})
CONFLICT_MINE = frozenset({"yours", "mine", "my version", "keep mine", "as i said", "meins"})
CONFLICT_DOCUMENT = frozenset({"the documents", "the document", "document", "the file", "the new one", "das dokument"})
CONFLICT_BOTH = frozenset({"both", "keep both", "both of them", "beide"})
_OPTION = re.compile(r"^(?:option )?([123])$")
Choice = Literal["current", "offered", "both"]


def _file_names(name: str) -> list[str]:
    """A file name as a reply could say it: full and without the extension, `_`/`-` as spaces, normalised."""
    spaced = re.sub(r"[_\-]+", " ", name)
    stem = spaced.rsplit(".", 1)[0] if "." in spaced else spaced
    return [n for n in dict.fromkeys((normalise_reply(spaced), normalise_reply(stem))) if len(n) >= 3]


def read_conflict_reply(
    text: str | None, *, kind: str, both_offered: bool, holder_name: str | None, offered_name: str
) -> Choice | None:
    """A clear choice for the conflict group in the last question (§3.17 item 4), or `None` (the expert's own words).

    `kind` is the group's kind (`expert` or `document`); `holder_name` is the holder document of a
    document-kind group. First match wins; a reply over 6 words or naming both files decides nothing.
    """
    reply = normalise_reply(text)
    if not reply or len(reply.split()) > REPLY_MAX_WORDS:
        return None
    expert = kind == "expert"
    if reply in CONFLICT_KEEP:
        return "current"
    if reply in CONFLICT_MINE:
        return "current" if expert else None
    if reply in CONFLICT_DOCUMENT:
        return "offered" if expert else None
    if reply in CONFLICT_BOTH:
        return "both" if expert and both_offered else None
    option = _OPTION.match(reply)
    if option is not None:
        number = option.group(1)
        if number == "1":
            return "current"
        if number == "2":
            return "offered"
        return "both" if expert and both_offered else None
    spoken = re.sub(r"[_\-]+", " ", text or "")
    named_offered = any(mentions(spoken, n) for n in _file_names(offered_name))
    named_holder = bool(holder_name) and any(mentions(spoken, n) for n in _file_names(holder_name or ""))
    if named_offered and not named_holder:
        return "offered"
    if named_holder and not named_offered and not expert:
        return "current"
    return None
