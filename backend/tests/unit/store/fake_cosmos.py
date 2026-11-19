"""A fake `azure.cosmos.aio` container client, so the Cosmos repository runs its contract offline (spec 15 §7).

Why: the Cosmos repository must pass the same contract as the memory one (AC-15.25), but unit tests
cannot reach Azure. A fake is only useful if it behaves like the real `ContainerProxy` where the
repository depends on it, so this one raises the SDK's own exception classes, honours `etag` with
`MatchConditions.IfNotModified`, adds the system fields (`_rid`, `_self`, `_etag`, `_attachments`,
`_ts`) and scopes queries to one partition.
What: `FakeContainer` with `read`, `read_item`, `create_item`, `replace_item`, `delete_item` and
`query_items` (a small subset of Cosmos SQL: projections with `AS`, `ARRAY_LENGTH`, `["key"]`
paths, `SELECT *`, `WHERE path = @param AND ...`, one `ORDER BY`). It records every query and can
be told to fail the next call or to look like a missing container or one with TTL off.
Must not: be imported by app code, or accept calls the real async SDK would reject (a query without
`partition_key`, or `enable_cross_partition_query`, which breaks the async client). Covers the fake
side of AC-15.11, AC-15.14, AC-15.19 and AC-15.25.
"""

from __future__ import annotations

import copy
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from azure.core import MatchConditions
from azure.cosmos import exceptions

PARTITION_KEY = "ownerId"
_UNDEFINED = object()
_PATH = re.compile(r'^c((?:\.\w+|\["\w+"\])*)$')
_SEGMENT = re.compile(r'\.(\w+)|\["(\w+)"\]')
_QUERY = re.compile(
    r"^SELECT (?P<proj>.+?) FROM c(?: WHERE (?P<where>.+?))?(?: ORDER BY (?P<order>c\S+) (?P<dir>ASC|DESC))?$",
    re.IGNORECASE,
)


def _segments(path: str) -> list[str]:
    match = _PATH.match(path.strip())
    if not match:
        raise exceptions.CosmosHttpResponseError(status_code=400, message=f"Syntax error near {path!r}")
    return [a or b for a, b in _SEGMENT.findall(match.group(1))]


def _resolve(doc: Any, segments: list[str]) -> Any:
    value = doc
    for key in segments:
        if not isinstance(value, dict) or key not in value:
            return _UNDEFINED
        value = value[key]
    return value


class _AsyncItems:
    """What `query_items` returns: an async iterable (not awaitable), like `AsyncItemPaged`."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def gen() -> AsyncIterator[dict[str, Any]]:
            for item in self._items:
                yield item

        return gen()


class FakeContainer:
    """In-memory stand-in for `azure.cosmos.aio.ContainerProxy` (partition key `/ownerId`)."""

    def __init__(self, *, container_id: str = "sessions", default_ttl: int | None = -1, missing: bool = False) -> None:
        self.id = container_id
        self.default_ttl = default_ttl
        self.missing = missing
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.queries: list[str] = []
        self.fail_next: BaseException | None = None

    # --- helpers for tests ---------------------------------------------------------------------

    def stored(self, owner_id: str, item_id: str) -> dict[str, Any] | None:
        """The stored document as Cosmos holds it (system fields included), or None."""
        doc = self.items.get((owner_id, item_id))
        return copy.deepcopy(doc) if doc is not None else None

    def put_raw(self, doc: dict[str, Any], partition: str | None = None) -> None:
        """Store a document exactly as given (e.g. one an older version wrote), by default in its own partition."""
        self.items[(partition or doc[PARTITION_KEY], doc["id"])] = copy.deepcopy(doc)

    def _guard(self) -> None:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        if self.missing:
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Resource Not Found")

    def _with_system_fields(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body.get("id"), str) or not body["id"]:
            raise exceptions.CosmosHttpResponseError(status_code=400, message="The input content is invalid: id")
        if not isinstance(body.get(PARTITION_KEY), str):
            raise exceptions.CosmosHttpResponseError(status_code=400, message="Partition key missing")
        ttl = body.get("ttl", _UNDEFINED)
        # Conservative: Cosmos accepts only a non-zero integer (or -1) as an item ttl.
        if ttl is not _UNDEFINED and (not isinstance(ttl, int) or isinstance(ttl, bool) or ttl == 0 or ttl < -1):
            raise exceptions.CosmosHttpResponseError(status_code=400, message="The value of 'ttl' is invalid")
        doc = copy.deepcopy(body)
        rid = uuid.uuid4().hex[:12]
        doc.update(
            {
                "_rid": rid,
                "_self": f"dbs/db/colls/{self.id}/docs/{rid}/",
                "_etag": f'"{uuid.uuid4()}"',
                "_attachments": "attachments/",
                "_ts": int(time.time()),
            }
        )
        return doc

    # --- the ContainerProxy surface the repository uses -------------------------------------------

    async def read(self, **kwargs: Any) -> dict[str, Any]:
        self._guard()
        props: dict[str, Any] = {"id": self.id, "partitionKey": {"paths": [f"/{PARTITION_KEY}"], "kind": "Hash"}}
        if self.default_ttl is not None:
            props["defaultTtl"] = self.default_ttl
        return props

    async def read_item(self, item: str, partition_key: str, **kwargs: Any) -> dict[str, Any]:
        self._guard()
        doc = self.items.get((partition_key, item))
        if doc is None:
            raise exceptions.CosmosResourceNotFoundError(
                status_code=404, message="Entity with the specified id does not exist"
            )
        return copy.deepcopy(doc)

    async def create_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self._guard()
        doc = self._with_system_fields(body)
        key = (doc[PARTITION_KEY], doc["id"])
        if key in self.items:
            raise exceptions.CosmosResourceExistsError(
                status_code=409, message="Entity with the specified id already exists"
            )
        self.items[key] = doc
        return copy.deepcopy(doc)

    async def replace_item(
        self,
        item: str,
        body: dict[str, Any],
        *,
        etag: str | None = None,
        match_condition: MatchConditions | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._guard()
        if body.get("id") != item:
            raise exceptions.CosmosHttpResponseError(status_code=400, message="id in body does not match")
        doc = self._with_system_fields(body)
        key = (doc[PARTITION_KEY], item)
        current = self.items.get(key)
        if current is None:
            raise exceptions.CosmosResourceNotFoundError(
                status_code=404, message="Entity with the specified id does not exist"
            )
        if match_condition == MatchConditions.IfNotModified and etag != current["_etag"]:
            raise exceptions.CosmosAccessConditionFailedError(
                status_code=412,
                message="Operation cannot be performed because one of the specified precondition is not met",
            )
        self.items[key] = doc
        return copy.deepcopy(doc)

    async def delete_item(self, item: str, partition_key: str, **kwargs: Any) -> None:
        self._guard()
        if self.items.pop((partition_key, item), None) is None:
            raise exceptions.CosmosResourceNotFoundError(
                status_code=404, message="Entity with the specified id does not exist"
            )

    def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        *,
        partition_key: str | None = None,
        **kwargs: Any,
    ) -> _AsyncItems:
        if "enable_cross_partition_query" in kwargs:
            raise TypeError("enable_cross_partition_query is not accepted by the async client")
        if partition_key is None:
            raise AssertionError("the store queries one partition only: pass partition_key=")
        self._guard()
        self.queries.append(query)
        params = {p["name"]: p["value"] for p in parameters or []}
        match = _QUERY.match(" ".join(query.split()))
        if not match:
            raise exceptions.CosmosHttpResponseError(status_code=400, message="Syntax error")
        docs = [copy.deepcopy(d) for (pk, _), d in self.items.items() if pk == partition_key]
        if match.group("where"):
            for clause in re.split(r"\s+AND\s+", match.group("where"), flags=re.IGNORECASE):
                left, right = (part.strip() for part in clause.split("="))
                if right not in params:
                    raise exceptions.CosmosHttpResponseError(status_code=400, message=f"Unknown parameter {right}")
                docs = [d for d in docs if _resolve(d, _segments(left)) == params[right]]
        if match.group("order"):
            order = _segments(match.group("order"))
            docs.sort(key=lambda d: str(_resolve(d, order)), reverse=match.group("dir").upper() == "DESC")
        return _AsyncItems([self._project(d, match.group("proj")) for d in docs])

    @staticmethod
    def _project(doc: dict[str, Any], projection: str) -> dict[str, Any]:
        if projection.strip() == "*":
            return doc
        out: dict[str, Any] = {}
        for part in projection.split(","):
            expr, _, alias = part.strip().partition(" AS ")
            expr = expr.strip()
            func = re.match(r"^ARRAY_LENGTH\((.+)\)$", expr, re.IGNORECASE)
            segments = _segments(func.group(1) if func else expr)
            value = _resolve(doc, segments)
            if func and value is not _UNDEFINED:
                value = len(value) if isinstance(value, list) else _UNDEFINED
            key = alias.strip() or segments[-1]
            if value is not _UNDEFINED:
                out[key] = value
        return out
