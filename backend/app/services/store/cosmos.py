"""The Cosmos DB store used in Azure (spec 15 §3.6, `STORE=cosmos`; architecture §5).

Why: the demo keeps every session and idea as one document in a serverless Cosmos container
partitioned by `/ownerId`, written whole with `If-Match` so two writers never silently overwrite
each other. Auth is Entra only (the account has local auth disabled), so there is no key to leak.
What: `CosmosRepository`, the storage primitives of `DocumentRepository` over an
`azure.cosmos.aio` container client: point reads and deletes within the owner's partition,
create, replace with `etag` + `MatchConditions.IfNotModified`, and partition-scoped queries (the
summary query projects only summary fields). SDK errors map to store errors (AC-15.19).
`open_cosmos(settings)` builds the client with `DefaultAzureCredential`; it is called from the
app lifespan, never at import time (AC-15.20, AC-15.21).
Must not: create the database or container (Bicep does; `check()` only reports), use a key,
pass `enable_cross_partition_query` (the async client rejects it; scope with `partition_key=`),
or select `c.messages` or `c.profile` whole in a list query (AC-15.14).
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.identity.aio import DefaultAzureCredential

from app.core.settings import Settings
from app.services.store.repository import (
    ConflictError,
    DocumentRepository,
    StoreHealth,
    StoreUnavailableError,
    owner_prefix,
)

logger = logging.getLogger(__name__)

# `value` is a reserved word in Cosmos SQL, hence `c.score["value"]`.
SUMMARY_QUERY = (
    "SELECT c.id, c.status, c.phase, "
    "c.profile.process.name AS processName, "
    "c.profile.process.cluster.code AS clusterCode, "
    'c.score["value"] AS score, '
    "ARRAY_LENGTH(c.messages) AS messageCount, "
    "c.createdAt, c.updatedAt, "
    "c.report.status AS reportStatus "
    "FROM c WHERE c.ownerId = @ownerId AND c.type = @type "
    "ORDER BY c.updatedAt DESC"
)
IDEAS_QUERY = "SELECT * FROM c WHERE c.ownerId = @ownerId AND c.type = @type ORDER BY c.createdAt DESC"
IDS_QUERY = "SELECT c.id, c.type FROM c WHERE c.ownerId = @ownerId"

# What counts as "unavailable": every SDK error (HTTP, auth, connection) plus socket errors.
_TRANSIENT = (AzureError, OSError, TimeoutError)


def _unavailable(error: BaseException, operation: str, owner_id: str) -> NoReturn:
    status = getattr(error, "status_code", None)
    logger.error(
        "store_unavailable",
        extra={
            "operation": operation,
            "owner": owner_prefix(owner_id),
            "status": status,
            "error": type(error).__name__,
        },
    )
    raise StoreUnavailableError(f"Cosmos {operation} failed ({type(error).__name__}, status {status})") from error


class CosmosRepository(DocumentRepository):
    """Sessions and ideas in one Cosmos container (partition key `/ownerId`)."""

    def __init__(
        self,
        container: ContainerProxy,
        *,
        retention_days: int,
        client: Any | None = None,
        credential: Any | None = None,
    ) -> None:
        super().__init__(retention_days=retention_days)
        self._container = container
        self._client = client
        self._credential = credential

    async def _read(self, owner_id: str, doc_id: str) -> dict[str, Any] | None:
        try:
            return dict(await self._container.read_item(item=doc_id, partition_key=owner_id))
        except exceptions.CosmosResourceNotFoundError:
            return None
        except _TRANSIENT as error:
            _unavailable(error, "read", owner_id)

    async def _create(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            return dict(await self._container.create_item(body=doc))
        except exceptions.CosmosResourceExistsError:
            raise ConflictError(f"document {doc['id']} already exists") from None
        except _TRANSIENT as error:
            _unavailable(error, "create", doc["ownerId"])

    async def _replace(self, doc: dict[str, Any], etag: str) -> dict[str, Any]:
        try:
            return dict(
                await self._container.replace_item(
                    item=doc["id"], body=doc, etag=etag, match_condition=MatchConditions.IfNotModified
                )
            )
        except (exceptions.CosmosAccessConditionFailedError, exceptions.CosmosResourceNotFoundError):
            # Changed (412) or deleted (404) since it was read: either way the caller must reload.
            raise ConflictError(f"document {doc['id']} changed since it was read") from None
        except _TRANSIENT as error:
            _unavailable(error, "replace", doc["ownerId"])

    async def _delete(self, owner_id: str, doc_id: str) -> bool:
        try:
            await self._container.delete_item(item=doc_id, partition_key=owner_id)
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
        except _TRANSIENT as error:
            _unavailable(error, "delete", owner_id)

    async def _query(self, query: str, owner_id: str, **params: str) -> list[dict[str, Any]]:
        """One partition only. The async SDK takes no `enable_cross_partition_query`."""
        parameters: list[dict[str, Any]] = [{"name": "@ownerId", "value": owner_id}]
        parameters += [{"name": f"@{name}", "value": value} for name, value in params.items()]
        try:
            return [
                dict(item)
                async for item in self._container.query_items(
                    query=query, parameters=parameters, partition_key=owner_id
                )
            ]
        except _TRANSIENT as error:
            _unavailable(error, "query", owner_id)

    async def _session_summaries(self, owner_id: str) -> list[dict[str, Any]]:
        return await self._query(SUMMARY_QUERY, owner_id, type="session")

    async def _ideas(self, owner_id: str) -> list[dict[str, Any]]:
        return await self._query(IDEAS_QUERY, owner_id, type="idea")

    async def _ids(self, owner_id: str) -> list[tuple[str, str]]:
        return [(row["id"], str(row.get("type"))) for row in await self._query(IDS_QUERY, owner_id)]

    async def check(self) -> StoreHealth:
        """Reachable, and TTL on (`defaultTtl` set) so item ttl is honoured. Never raises."""
        try:
            properties = await self._container.read()
        except exceptions.CosmosResourceNotFoundError:
            return StoreHealth(ok=False, ttl_enabled=None, detail="container not found (Bicep creates it)")
        except Exception as error:  # a health report must never fail start-up
            return StoreHealth(ok=False, ttl_enabled=None, detail=f"unreachable: {type(error).__name__}")
        if properties.get("defaultTtl") is None:
            return StoreHealth(ok=False, ttl_enabled=False, detail="container TTL is off: item ttl is ignored")
        return StoreHealth(ok=True, ttl_enabled=True, detail="ok")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._credential is not None:
            await self._credential.close()


async def open_cosmos(settings: Settings) -> CosmosRepository:
    """Build the client from settings with Entra auth (`az login` locally, managed identity in Azure)."""
    if not settings.cosmos_endpoint:
        raise ValueError("COSMOS_ENDPOINT is required when STORE=cosmos")
    if settings.azure_client_id:
        credential = DefaultAzureCredential(managed_identity_client_id=settings.azure_client_id)
    else:
        credential = DefaultAzureCredential()
    client = CosmosClient(settings.cosmos_endpoint, credential=credential)
    container = client.get_database_client(settings.cosmos_database).get_container_client(settings.cosmos_container)
    return CosmosRepository(
        container, retention_days=settings.session_retention_days, client=client, credential=credential
    )
