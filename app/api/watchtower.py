import asyncio
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchtower")


class WatchtowerStatus(BaseModel):
    running: bool
    interval: int
    containers_scanned: int | None = None
    containers_updated: int | None = None


def _parse_prometheus_metric(text: str, metric_name: str) -> int | None:
    """Extract a metric value from Prometheus-style text output."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith(metric_name):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(float(parts[-1]))
                except ValueError:
                    pass
    return None


def _fetch_watchtower_metrics() -> WatchtowerStatus:
    """Blocking call to query Watchtower HTTP API. Runs in a thread."""
    url = f"{settings.WATCHTOWER_URL}/v1/metrics"
    token = settings.WATCHTOWER_TOKEN

    try:
        req = Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")

        scanned = _parse_prometheus_metric(body, "watchtower_containers_scanned")
        updated = _parse_prometheus_metric(body, "watchtower_containers_updated")

        return WatchtowerStatus(
            running=True,
            interval=settings.WATCHTOWER_INTERVAL,
            containers_scanned=scanned,
            containers_updated=updated,
        )

    except (URLError, OSError, TimeoutError) as exc:
        logger.debug("Watchtower not reachable: %s", exc)
        return WatchtowerStatus(
            running=False,
            interval=settings.WATCHTOWER_INTERVAL,
        )


@router.get("/status", response_model=WatchtowerStatus)
async def watchtower_status() -> WatchtowerStatus:
    """Query the Watchtower HTTP API for status and metrics."""
    return await asyncio.to_thread(_fetch_watchtower_metrics)
