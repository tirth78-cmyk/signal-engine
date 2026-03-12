"""
HubSpot CRM Connector — Pushes signals to HubSpot Custom Objects,
associates with Companies, and triggers workflows.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import SignalRecord, SignalStatus, SignalType
from src.utils.logging import get_logger
from config.settings import settings

logger = get_logger("connector.hubspot")


class HubSpotConnector:
    """
    HubSpot CRM integration:
    - Creates/updates Custom Object records (Signals)
    - Associates signals with Company records
    - Batch operations for throughput
    - Handles rate limiting (100 req/10s)
    """

    BASE_URL = "https://api.hubapi.com"

    # Signal Custom Object schema (13 properties)
    SIGNAL_PROPERTIES = [
        {"name": "signal_title", "label": "Signal Title", "type": "string", "fieldType": "text"},
        {"name": "signal_type", "label": "Signal Type", "type": "enumeration", "fieldType": "select",
         "options": [{"label": t.value.replace("_", " ").title(), "value": t.value} for t in SignalType]},
        {"name": "signal_description", "label": "Description", "type": "string", "fieldType": "textarea"},
        {"name": "source_url", "label": "Source URL", "type": "string", "fieldType": "text"},
        {"name": "source_type", "label": "Source Type", "type": "string", "fieldType": "text"},
        {"name": "source_name", "label": "Source Name", "type": "string", "fieldType": "text"},
        {"name": "confidence_score", "label": "AI Confidence", "type": "number", "fieldType": "number"},
        {"name": "recency_score", "label": "Recency Score", "type": "number", "fieldType": "number"},
        {"name": "relevance_score", "label": "Relevance Score", "type": "number", "fieldType": "number"},
        {"name": "authority_score", "label": "Authority Score", "type": "number", "fieldType": "number"},
        {"name": "composite_score", "label": "Composite Score", "type": "number", "fieldType": "number"},
        {"name": "signal_status", "label": "Status", "type": "string", "fieldType": "text"},
        {"name": "published_date", "label": "Published Date", "type": "datetime", "fieldType": "date"},
    ]

    def __init__(self):
        self.api_key = settings.hubspot.api_key
        self._rate_limiter = asyncio.Semaphore(10)  # 10 concurrent requests

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=self._headers(),
            timeout=30.0,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    async def _api_call(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
        """Make a rate-limited API call."""
        async with self._rate_limiter:
            response = await getattr(client, method)(url, **kwargs)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 10))
                logger.warning("hubspot_rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                response = await getattr(client, method)(url, **kwargs)
            response.raise_for_status()
            return response.json() if response.text else {}

    # ─── Custom Object Schema ────────────────────────────────────────────────

    async def ensure_custom_object_schema(self):
        """Create the Signals custom object schema if it doesn't exist."""
        async with self._get_client() as client:
            try:
                # Check if schema exists
                await self._api_call(
                    client, "get",
                    f"/crm/v3/schemas/{settings.hubspot.signal_object_type}"
                )
                logger.info("custom_object_schema_exists")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Create schema
                    schema = {
                        "name": settings.hubspot.signal_object_type,
                        "labels": {"singular": "Signal", "plural": "Signals"},
                        "primaryDisplayProperty": "signal_title",
                        "requiredProperties": ["signal_title", "signal_type"],
                        "properties": self.SIGNAL_PROPERTIES,
                        "associatedObjects": ["companies", "contacts"],
                    }
                    await self._api_call(client, "post", "/crm/v3/schemas", json=schema)
                    logger.info("custom_object_schema_created")
                else:
                    raise

    # ─── Signal CRUD ─────────────────────────────────────────────────────────

    async def push_signal(self, signal: SignalRecord) -> Optional[str]:
        """Push a single signal to HubSpot as a Custom Object."""
        if not self.api_key:
            logger.warning("hubspot_api_key_not_configured")
            return None

        properties = {
            "signal_title": signal.title[:200],
            "signal_type": signal.signal_type.value,
            "signal_description": (signal.description or "")[:10000],
            "source_url": signal.source_url or "",
            "source_type": signal.source_type.value,
            "source_name": signal.source_name or "",
            "confidence_score": round(signal.confidence * 100, 1),
            "recency_score": signal.recency_score,
            "relevance_score": signal.relevance_score,
            "authority_score": signal.authority_score,
            "composite_score": signal.composite_score,
            "signal_status": signal.status.value,
        }

        if signal.published_at:
            properties["published_date"] = signal.published_at.strftime("%Y-%m-%d")

        async with self._get_client() as client:
            try:
                result = await self._api_call(
                    client, "post",
                    f"/crm/v3/objects/{settings.hubspot.signal_object_type}",
                    json={"properties": properties},
                )
                hubspot_id = result.get("id")
                signal.hubspot_object_id = hubspot_id
                signal.hubspot_synced_at = datetime.now(timezone.utc)
                signal.status = SignalStatus.PUSHED

                logger.info("signal_pushed", signal_id=signal.id, hubspot_id=hubspot_id)

                # Associate with company if we have a HubSpot company ID
                if signal.company_hubspot_id:
                    await self._associate_signal_to_company(
                        client, hubspot_id, signal.company_hubspot_id
                    )

                return hubspot_id

            except Exception as e:
                signal.status = SignalStatus.FAILED
                logger.error("signal_push_failed", signal_id=signal.id, error=str(e))
                return None

    async def push_batch(self, signals: list[SignalRecord]) -> dict:
        """Push multiple signals in batch."""
        results = {"success": 0, "failed": 0, "ids": []}

        # HubSpot batch API accepts up to 100 items
        batch_size = settings.hubspot.batch_size
        for i in range(0, len(signals), batch_size):
            batch = signals[i:i + batch_size]

            inputs = []
            for signal in batch:
                inputs.append({
                    "properties": {
                        "signal_title": signal.title[:200],
                        "signal_type": signal.signal_type.value,
                        "signal_description": (signal.description or "")[:10000],
                        "source_url": signal.source_url or "",
                        "source_type": signal.source_type.value,
                        "confidence_score": round(signal.confidence * 100, 1),
                        "composite_score": signal.composite_score,
                        "signal_status": signal.status.value,
                    }
                })

            async with self._get_client() as client:
                try:
                    result = await self._api_call(
                        client, "post",
                        f"/crm/v3/objects/{settings.hubspot.signal_object_type}/batch/create",
                        json={"inputs": inputs},
                    )
                    created = result.get("results", [])
                    results["success"] += len(created)
                    results["ids"].extend([r["id"] for r in created])

                    # Update signal records
                    for j, record in enumerate(created):
                        if j < len(batch):
                            batch[j].hubspot_object_id = record["id"]
                            batch[j].hubspot_synced_at = datetime.now(timezone.utc)
                            batch[j].status = SignalStatus.PUSHED

                except Exception as e:
                    results["failed"] += len(batch)
                    logger.error("batch_push_failed", batch_start=i, error=str(e))

            await asyncio.sleep(0.5)  # Rate limit buffer

        logger.info("batch_push_complete", **results)
        return results

    # ─── Company Lookup & Association ────────────────────────────────────────

    async def find_company(self, company_name: str, domain: str = "") -> Optional[str]:
        """Find a HubSpot company by name or domain."""
        async with self._get_client() as client:
            # Search by domain first (more reliable)
            if domain:
                try:
                    result = await self._api_call(
                        client, "post",
                        "/crm/v3/objects/companies/search",
                        json={
                            "filterGroups": [{
                                "filters": [{
                                    "propertyName": "domain",
                                    "operator": "EQ",
                                    "value": domain,
                                }]
                            }],
                            "limit": 1,
                        },
                    )
                    if result.get("results"):
                        return result["results"][0]["id"]
                except Exception:
                    pass

            # Fallback: search by name
            try:
                result = await self._api_call(
                    client, "post",
                    "/crm/v3/objects/companies/search",
                    json={
                        "filterGroups": [{
                            "filters": [{
                                "propertyName": "name",
                                "operator": "CONTAINS_TOKEN",
                                "value": company_name,
                            }]
                        }],
                        "limit": 1,
                    },
                )
                if result.get("results"):
                    return result["results"][0]["id"]
            except Exception:
                pass

        return None

    async def _associate_signal_to_company(
        self, client: httpx.AsyncClient, signal_id: str, company_id: str
    ):
        """Create an association between a signal and a company."""
        try:
            await self._api_call(
                client, "put",
                f"/crm/v3/objects/{settings.hubspot.signal_object_type}/{signal_id}/associations/companies/{company_id}/signal_to_company",
            )
            logger.info("signal_associated", signal_id=signal_id, company_id=company_id)
        except Exception as e:
            logger.warning("association_failed", signal_id=signal_id, error=str(e))

    # ─── Health Check ────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """Check HubSpot API connectivity."""
        if not self.api_key:
            return {"status": "not_configured", "message": "API key not set"}

        async with self._get_client() as client:
            try:
                result = await self._api_call(client, "get", "/crm/v3/objects/companies?limit=1")
                return {"status": "healthy", "message": "Connected to HubSpot"}
            except Exception as e:
                return {"status": "unhealthy", "message": str(e)}
