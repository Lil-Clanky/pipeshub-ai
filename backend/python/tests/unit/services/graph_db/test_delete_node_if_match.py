"""``delete_node_if_match``: the statement each store runs, its retry on ArangoDB, and the interface default."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.graph_db.arango import arango_http_provider as arango_module
from app.services.graph_db.arango.arango_http_provider import ArangoHTTPProvider
from app.services.graph_db.interface.graph_db_provider import IGraphDBProvider
from app.services.graph_db.neo4j.neo4j_provider import Neo4jProvider

CONFLICT = RuntimeError('Query failed (status=409): {"errorMessage":"write-write conflict","errorNum":1200}')


@pytest.fixture
def arango(monkeypatch: pytest.MonkeyPatch) -> ArangoHTTPProvider:
    monkeypatch.setattr(arango_module.asyncio, "sleep", AsyncMock())
    p = ArangoHTTPProvider(logger=MagicMock(spec=logging.Logger), config_service=MagicMock())
    p.http_client = AsyncMock()
    return p


@pytest.fixture
def neo4j() -> Neo4jProvider:
    p = Neo4jProvider(logger=MagicMock(spec=logging.Logger), config_service=MagicMock())
    p.client = AsyncMock()
    return p


class TestArango:
    async def test_every_expected_field_is_a_filter_and_none_means_absent(self, arango) -> None:
        arango.http_client.execute_aql = AsyncMock(return_value=[1])
        assert await arango.delete_node_if_match("k", "things", {"a": 1, "b": None}) is True
        query = arango.http_client.execute_aql.await_args.args[0]
        binds = arango.http_client.execute_aql.await_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in query and "FILTER doc[@f1] == null" in query and "REMOVE doc IN @@collection" in query
        assert binds["v0"] == 1 and "v1" not in binds and binds["key"] == "k"

    async def test_no_match_reports_false(self, arango) -> None:
        arango.http_client.execute_aql = AsyncMock(return_value=[])
        assert await arango.delete_node_if_match("k", "things", {"a": 1}) is False

    async def test_a_conflict_is_retried(self, arango) -> None:
        arango.http_client.execute_aql = AsyncMock(side_effect=[CONFLICT, [1]])
        assert await arango.delete_node_if_match("k", "things", {"a": 1}) is True
        assert arango.http_client.execute_aql.await_count == 2

    async def test_an_empty_expectation_raises_before_any_query(self, arango) -> None:
        with pytest.raises(ValueError, match="expectation"):
            await arango.delete_node_if_match("k", "things", {})
        arango.http_client.execute_aql.assert_not_awaited()


class TestNeo4j:
    async def test_the_lock_comes_first_and_the_expectation_gates_the_delete(self, neo4j) -> None:
        neo4j.client.execute_query = AsyncMock(return_value=[{"n": 1}])
        assert await neo4j.delete_node_if_match("k", "things", {"a": 1, "b": None}) is True
        query = neo4j.client.execute_query.await_args.args[0]
        params = neo4j.client.execute_query.await_args.kwargs["parameters"]
        assert query.index("SET n.") < query.index("WHERE") < query.index("DELETE n")
        assert "n[$f0] = $v0" in query and "n[$f1] IS NULL" in query
        assert params["v0"] == 1 and "v1" not in params

    async def test_no_row_reports_false(self, neo4j) -> None:
        neo4j.client.execute_query = AsyncMock(return_value=[])
        assert await neo4j.delete_node_if_match("k", "things", {"a": 1}) is False

    async def test_an_empty_expectation_raises_before_any_query(self, neo4j) -> None:
        with pytest.raises(ValueError, match="expectation"):
            await neo4j.delete_node_if_match("k", "things", {})
        neo4j.client.execute_query.assert_not_awaited()


async def test_a_store_without_it_refuses_instead_of_deleting() -> None:
    with pytest.raises(NotImplementedError):
        await IGraphDBProvider.delete_node_if_match(MagicMock(), "k", "things", {"a": 1})
