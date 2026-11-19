"""Strict-mode `response_format` payloads for Azure Structured Outputs (spec 11 §3.6).

Why: Azure runs the schema inside the decoder, and its strict subset is narrow: every object must be
closed (`additionalProperties: false`) and list all its properties as required. Pydantic's schema
is neither, and a schema strict mode rejects fails only in a live call. This module turns any
Pydantic model into a strict-legal schema, and refuses, in a unit test instead of in production,
the shapes strict mode cannot express (recursion, `dict[str, X]` fields).
What: `strict_json_schema(model, name)` inlines every `$defs` reference (a sibling `description`
wins), closes every object, removes the top-level `title`, and returns the whole
`{"type": "json_schema", "json_schema": {...}}` envelope so the call site cannot get the wrapper
wrong. Implements spec 11, AC-11.18 to AC-11.20.
Must not: import anything from the engine (it sits at the bottom of it, architecture §3.1) or
change what Pydantic writes for optional fields (`anyOf` with `null` is what strict mode wants).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REF_PREFIX = "#/$defs/"


def _inline_refs(node: Any, defs: dict[str, Any], model: str, path: tuple[str, ...], stack: tuple[str, ...]) -> Any:
    """Replace every `$ref` into `$defs` with the definition itself; refuse a reference cycle."""
    if isinstance(node, list):
        return [_inline_refs(item, defs, model, (*path, str(i)), stack) for i, item in enumerate(node)]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        target_name = ref[len(_REF_PREFIX) :]
        if target_name in stack:
            raise ValueError(
                f"{model}: recursive model {target_name!r} at {_readable(path)}; strict mode cannot express it"
            )
        merged = dict(_inline_refs(defs[target_name], defs, model, path, (*stack, target_name)))
        merged.update({k: _inline_refs(v, defs, model, (*path, k), stack) for k, v in node.items() if k != "$ref"})
        return merged
    return {key: _inline_refs(value, defs, model, (*path, key), stack) for key, value in node.items()}


def _harden(node: Any, model: str, path: tuple[str, ...]) -> Any:
    """Close every object and make all its properties required; refuse open objects."""
    if isinstance(node, list):
        return [_harden(item, model, (*path, str(i))) for i, item in enumerate(node)]
    if not isinstance(node, dict):
        return node
    out = {key: _harden(value, model, (*path, key)) for key, value in node.items()}
    if out.get("type") == "object":
        if isinstance(out.get("properties"), dict):
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        elif out.get("additionalProperties", False) is not False:
            raise ValueError(
                f"{model}: open object (a dict field) at {_readable(path)}; strict mode needs fixed properties"
            )
    return out


def _readable(path: tuple[str, ...]) -> str:
    """A schema path as field names: `properties` and combinator noise dropped (`root.children.items`)."""
    parts = [p for p in path if p not in ("properties", "anyOf", "allOf", "oneOf") and not p.isdigit()]
    return ".".join(parts) or "(root)"


def strict_json_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    """The `response_format` payload for `model`, under the schema name `name`.

    Raises `ValueError` for a bad name, a recursive model or a `dict[str, X]` field, naming the path.
    """
    if not _NAME_RE.match(name):
        raise ValueError(f"schema name must match {_NAME_RE.pattern}")
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    if "$ref" in raw:  # Pydantic moves a self-referencing root model into `$defs`
        raise ValueError(f"{model.__name__}: recursive model at (root); strict mode cannot express it")
    schema = _harden(_inline_refs(raw, defs, model.__name__, (), ()), model.__name__, ())
    schema.pop("title", None)
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
