"""``delete_node_if_match`` against a real Neo4j and a real ArangoDB (PostgreSQL: ``postgres/test_core.py``).

The node goes only while every expected field still holds its value (``None`` means absent), and a call
with no expectation raises instead of deleting unconditionally.

Runs on Neo4j and ArangoDB (backend-matrix). Environment: NEO4J_IT_URI, NEO4J_IT_PASSWORD, ARANGO_IT_URL,
ARANGO_IT_PASSWORD.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import TYPE_CHECKING

import pytest

from app.config.constants.arangodb import CollectionNames
from tests.integration.real_graph import (
    backend_unavailable,
    connect_arango,
    connect_neo4j,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.services.graph_db.interface.graph_db_provider import IGraphDBProvider

pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]

ARANGO_DB = "delete_if_match_it"
COLLECTION = CollectionNames.VIRTUAL_RECORD_TO_DOC_ID_MAPPING.value
logger = logging.getLogger("delete-if-match-it")


@pytest.fixture(params=["neo4j", "arango"])
async def graph(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[IGraphDBProvider, str]]:
    async with contextlib.AsyncExitStack() as cleanup:
        try:
            provider = await (
                connect_neo4j(logger, monkeypatch) if request.param == "neo4j"
                else connect_arango(logger, ARANGO_DB)
            )
        except Exception as exc:
            backend_unavailable(request.param, exc)
        disconnect = getattr(provider, "disconnect", None)
        if disconnect is not None:
            cleanup.push_async_callback(disconnect)
        run = uuid.uuid4().hex[:10]
        yield provider, run
        await provider.delete_nodes([f"{run}-a", f"{run}-b", f"{run}-c"], COLLECTION)


async def _put(provider: IGraphDBProvider, key: str, **fields: str | int | None) -> None:
    assert await provider.batch_upsert_nodes(
        [{"id": key, "orgId": "org-it", "virtualRecordId": key, "documentId": "doc-1", "record_doc_id": "doc-1",
          "fileSizeBytes": 1, **fields}],
        COLLECTION,
    )


@pytest.mark.asyncio
async def test_the_node_goes_only_while_the_expectation_holds(graph: tuple[IGraphDBProvider, str]) -> None:
    provider, run = graph
    key = f"{run}-a"
    await _put(provider, key, storedRun="run-1")
    assert await provider.delete_node_if_match(key, COLLECTION, {"storedRun": "run-2"}) is False
    assert await provider.get_document(key, COLLECTION) is not None
    assert await provider.delete_node_if_match(key, COLLECTION, {"storedRun": "run-1", "documentId": "other"}) is False
    assert await provider.get_document(key, COLLECTION) is not None
    assert await provider.delete_node_if_match(key, COLLECTION, {"storedRun": "run-1", "documentId": "doc-1"}) is True
    assert await provider.get_document(key, COLLECTION) is None
    assert await provider.delete_node_if_match(key, COLLECTION, {"storedRun": "run-1"}) is False


@pytest.mark.asyncio
async def test_none_expects_the_field_absent(graph: tuple[IGraphDBProvider, str]) -> None:
    provider, run = graph
    present, absent = f"{run}-a", f"{run}-b"
    await _put(provider, present, storedRun="run-1")
    await _put(provider, absent)
    assert await provider.delete_node_if_match(present, COLLECTION, {"storedRun": None}) is False
    assert await provider.get_document(present, COLLECTION) is not None
    assert await provider.delete_node_if_match(absent, COLLECTION, {"storedRun": None}) is True
    assert await provider.get_document(absent, COLLECTION) is None


@pytest.mark.asyncio
async def test_an_empty_expectation_raises_and_deletes_nothing(graph: tuple[IGraphDBProvider, str]) -> None:
    provider, run = graph
    key = f"{run}-a"
    await _put(provider, key)
    with pytest.raises(ValueError, match="expectation"):
        await provider.delete_node_if_match(key, COLLECTION, {})
    assert await provider.get_document(key, COLLECTION) is not None


@pytest.mark.asyncio
async def test_of_concurrent_deletes_exactly_one_applies(graph: tuple[IGraphDBProvider, str]) -> None:
    provider, run = graph
    for round_ in range(3):
        key = f"{run}-a"
        await _put(provider, key, storedRun="run-1")
        results = await asyncio.gather(*(
            provider.delete_node_if_match(key, COLLECTION, {"storedRun": "run-1"}) for _ in range(5)
        ), return_exceptions=True)
        assert [r for r in results if r is True] == [True], (round_, results)
