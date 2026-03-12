"""Tests for the FastAPI endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoints:

    @pytest.mark.asyncio
    async def test_root(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Improzo Signal Engine"
        assert data["status"] == "running"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_health(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime_pct" in data
        assert "signals_today" in data

    @pytest.mark.asyncio
    async def test_scrapers(self, client):
        response = await client.get("/scrapers")
        assert response.status_code == 200
        data = response.json()
        assert "scrapers" in data
        assert len(data["scrapers"]) > 0


class TestSignalEndpoints:

    @pytest.mark.asyncio
    async def test_list_signals(self, client):
        response = await client.get("/signals")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_signals_with_filters(self, client):
        response = await client.get("/signals?status=verified&limit=10")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent_signal(self, client):
        response = await client.get("/signals/nonexistent-id")
        assert response.status_code == 404


class TestPipelineEndpoints:

    @pytest.mark.asyncio
    async def test_pipeline_metrics(self, client):
        response = await client.get("/pipeline/metrics?hours=24")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_last_run(self, client):
        response = await client.get("/pipeline/last-run")
        assert response.status_code == 200


class TestAnalyticsEndpoints:

    @pytest.mark.asyncio
    async def test_distribution(self, client):
        response = await client.get("/analytics/distribution")
        assert response.status_code == 200
        assert "distribution" in response.json()

    @pytest.mark.asyncio
    async def test_top_companies(self, client):
        response = await client.get("/analytics/top-companies?limit=10")
        assert response.status_code == 200
        assert "companies" in response.json()

    @pytest.mark.asyncio
    async def test_source_stats(self, client):
        response = await client.get("/analytics/source-stats")
        assert response.status_code == 200
        assert "sources" in response.json()
