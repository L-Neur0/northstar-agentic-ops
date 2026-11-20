"""The READ_DOCUMENT output model, generated from the field registry (spec 17 §3.7).

Why: the model may only propose what a document is allowed to propose, and a hand-written schema
would drift from the registry: a new field would be silently ignored, or a flag or a none row
could become expressible. Generating the model from `proposal_keys()` and the `FieldSpec`s means a
field added with `propose=True` appears here with no edit, and every value carries the quote that
the quote check (`quotes.py`) verifies.
What: `build_read_document_model(process_specs, step_specs)` (pure, used by the tests with a
registry double) and `read_document_model()`, the cached model for the real registry. Kind map:
text → `{value, quote}`; list → `[{value, quote}]`; scalar object → its sub-fields plus `quote`;
object of lists (S07) → each list as `[{value, quote}]`; object_list → rows with `quote`.
Must not: express a bool sub-field (`none_identified`, `estimated`) or a none row: the absence of
something in a document is not the expert saying "there are none". No object is built at import
time. Spec 17 §3.7; AC-17.20 to AC-17.22. Amendment §3.18 item 4: `document_role` replaces
`document_kind`, and `target_step`, `target_named_by`, `file_description` and `target_cells` (the
step leaves without `name`, all optional) are added; `read_image_model()` adds `visible_text` and
`image_summary` (§3.19 item 5). AC-17.47, AC-17.56.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..domain.field_spec import PROFILE_SPECS, STEP_SPECS, FieldSpec, SubFieldSpec

DocumentRole = Literal["whole_process", "step_output_example", "step_input_example", "step_material", "other"]
TargetNamedBy = Literal["focus", "document", "expert"]
STEP_SCOPED: frozenset[str] = frozenset({"step_output_example", "step_input_example", "step_material", "other"})


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QText(_Closed):
    """One text value and the words copied from the document that support it."""

    value: str
    quote: str


class QNumber(_Closed):
    value: int | None = None
    quote: str


def _sub_type(sub: SubFieldSpec) -> Any:
    if sub.kind == "number":
        return int | None
    if sub.kind == "list":
        return list[QText]
    return str | None


def _sub_default(sub: SubFieldSpec) -> Any:
    return Field(default_factory=list) if sub.kind == "list" else None


def _object_model(spec: FieldSpec, name: str, *, row: bool) -> type[BaseModel]:
    subs = [s for s in spec.subfields if s.kind != "bool"]
    fields: dict[str, Any] = {s.key: (_sub_type(s), _sub_default(s)) for s in subs}
    if row or any(s.kind != "list" for s in subs):
        fields["quote"] = (str, ...)
    return create_model(name, __base__=_Closed, **fields)


def _field(spec: FieldSpec) -> tuple[Any, Any]:
    """`(annotation, default)` of one proposable field in the output model."""
    if spec.kind == "text":
        return QText | None, None
    if spec.kind == "number":
        return QNumber | None, None
    if spec.kind == "list":
        return list[QText], Field(default_factory=list)
    if spec.kind == "object":
        return _object_model(spec, f"Q{spec.id}", row=False) | None, None
    return list[_object_model(spec, f"Q{spec.id}Row", row=True)], Field(default_factory=list)


def build_read_document_model(
    process_specs: Sequence[FieldSpec], step_specs: Sequence[FieldSpec], *, image: bool = False
) -> type[BaseModel]:
    """The output model for these registry entries: only `propose=True` fields, by leaf, in registry order."""
    step_fields: dict[str, Any] = {}
    cell_fields: dict[str, Any] = {}
    for spec in step_specs:
        if not spec.propose:
            continue
        step_fields[spec.key] = (QText, ...) if spec.key == "name" else _field(spec)
        if spec.key != "name":
            cell_fields[spec.key] = _field(spec)
    step_model = create_model("QStep", __base__=_Closed, **step_fields)
    cells_model = create_model("QCells", __base__=_Closed, **cell_fields)
    fields: dict[str, Any] = {}
    if image:
        fields["visible_text"] = (str, "")
        fields["image_summary"] = (str, "")
    fields["document_role"] = (DocumentRole, "other")
    fields["target_step"] = (int | None, None)
    fields["target_named_by"] = (TargetNamedBy | None, None)
    fields["file_description"] = (QText | None, None)
    for spec in process_specs:
        if spec.is_process and spec.propose:
            fields[spec.leaf] = _field(spec)
    fields["steps"] = (list[step_model], Field(default_factory=list))
    fields["target_cells"] = (cells_model | None, None)
    name = "ReadImageOut" if image else "ReadDocumentOut"
    return create_model(name, __base__=_Closed, **fields)


@cache
def read_document_model() -> type[BaseModel]:
    """`ReadDocumentOut` for the real registry, built once on first use."""
    return build_read_document_model(PROFILE_SPECS, STEP_SPECS)


@cache
def read_image_model() -> type[BaseModel]:
    """`ReadDocumentOut` plus `visible_text` and `image_summary` (spec 17 §3.19 item 5), built once."""
    return build_read_document_model(PROFILE_SPECS, STEP_SPECS, image=True)
