"""AI-generated compare summary via Claude API."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.car import Car
    from app.services.depreciation import DepreciationResult

logger = logging.getLogger(__name__)


async def generate_compare_summary(
    cars: list["Car"],
    depreciation_results: dict[str, "DepreciationResult"],
) -> str:
    """Generate an AI summary comparing cars from a buy-timing perspective.

    Returns a fallback string if the API key is missing or the call fails.
    """
    from app.settings import settings

    if not settings.anthropic_api_key:
        return "AI summary unavailable (Anthropic API key not configured)."

    lines = ["Compare the following cars from a buy-timing perspective:\n"]
    for car in cars:
        dep = depreciation_results.get(str(car.id))
        status = dep.buy_window_status if dep else "unknown"
        floor = f"~${dep.fit.floor / 1000:.0f}k" if dep and dep.fit else "unknown"
        lines.append(
            f"- {car.make} {car.model} {car.trim}: "
            f"buy window = {status}, predicted floor = {floor}, "
            f"MSRP = ${car.msrp_original:,}, "
            f"production = {car.production_count or 'unknown'}, "
            f"{'naturally aspirated' if car.is_naturally_aspirated else 'turbocharged'}"
        )
    lines.append(
        "\nWhich is the better buy right now and why? "
        "Answer in 2–3 sentences, be direct and specific."
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        return str(message.content[0].text)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("Anthropic API call failed: %s", exc)
        return "AI summary temporarily unavailable."
