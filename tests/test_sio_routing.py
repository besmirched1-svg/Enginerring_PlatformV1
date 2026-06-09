"""Test that route_event_to_socketio routes events to correct namespaces."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_evaluation_event_routed_to_default_namespace():
    """evaluation_complete events go to /optimizer as score_update
    AND to / (default) as the original event name for dashboard.html."""
    from app.realtime.events import route_event_to_socketio

    payload = {
        "machine_name": "test_unit",
        "composite_score": 0.91,
        "structural_stability": 0.94,
        "material_efficiency": 0.87,
        "manufacturing_simplicity": 0.82,
    }

    with patch("app.realtime.events.emit_optimizer_event", new_callable=AsyncMock) as mock_opt, \
         patch("app.realtime.events.emit_default_event", new_callable=AsyncMock) as mock_def:

        await route_event_to_socketio("evaluation_complete", payload)

        mock_opt.assert_awaited_once_with("score_update", payload)
        mock_def.assert_awaited_once_with("evaluation_complete", payload)


@pytest.mark.asyncio
async def test_score_event_routed():
    """score_update also hits both paths."""
    from app.realtime.events import route_event_to_socketio

    payload = {"score": 0.85}

    with patch("app.realtime.events.emit_optimizer_event", new_callable=AsyncMock) as mock_opt, \
         patch("app.realtime.events.emit_default_event", new_callable=AsyncMock) as mock_def:

        await route_event_to_socketio("score_update", payload)

        mock_opt.assert_awaited_once_with("score_update", payload)
        mock_def.assert_awaited_once_with("score_update", payload)


@pytest.mark.asyncio
async def test_revision_promoted_routed():
    """revision_promoted goes to /cad as stl_ready AND to default."""
    from app.realtime.events import route_event_to_socketio

    payload = {"revision_id": "rev_abc", "stl_url": "/outputs/test.stl"}

    with patch("app.realtime.events.emit_cad_event", new_callable=AsyncMock) as mock_cad, \
         patch("app.realtime.events.emit_default_event", new_callable=AsyncMock) as mock_def:

        await route_event_to_socketio("revision_promoted", payload)

        mock_cad.assert_awaited_once_with("stl_ready", payload)
        mock_def.assert_awaited_once_with("revision_promoted", payload)


@pytest.mark.asyncio
async def test_telemetry_event_routed():
    """telemetry events go to /telemetry namespace."""
    from app.realtime.events import route_event_to_socketio

    payload = {"session_id": "sess_1"}

    with patch("app.realtime.events.emit_telemetry_event", new_callable=AsyncMock) as mock_tel:

        await route_event_to_socketio("telemetry_ingested", payload)

        mock_tel.assert_awaited_once_with("telemetry_ingested", payload)


@pytest.mark.asyncio
async def test_unknown_event_falls_back_to_optimizer():
    """Unrecognized event types fall back to /optimizer."""
    from app.realtime.events import route_event_to_socketio

    payload = {"foo": "bar"}

    with patch("app.realtime.events.emit_optimizer_event", new_callable=AsyncMock) as mock_opt:

        await route_event_to_socketio("some_random_event", payload)

        mock_opt.assert_awaited_once_with("some_random_event", payload)
