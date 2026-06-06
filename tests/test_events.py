import pytest
import json
from unittest.mock import Mock, patch
from app.core.events import (
    EventBus, NullEventBus, EventMetrics,
    get_event_bus, get_event_metrics, EVENTS_CHANNEL
)


class TestEventMetrics:
    """Test event metrics tracking."""

    def test_record_success(self):
        """Metrics track successful publications."""
        metrics = EventMetrics()
        metrics.record_success()
        metrics.record_success()

        m = metrics.get_metrics()
        assert m["total_published"] == 2
        assert m["total_failed"] == 0

    def test_record_failure(self):
        """Metrics track failed publications."""
        metrics = EventMetrics()
        metrics.record_failure("test_event", "connection refused")

        m = metrics.get_metrics()
        assert m["total_failed"] == 1
        assert len(m["recent_failures"]) == 1
        assert m["recent_failures"][0]["type"] == "test_event"
        assert "timestamp" in m["recent_failures"][0]

    def test_max_failed_events_tracked(self):
        """Only recent 10 failures are retained."""
        metrics = EventMetrics()
        for i in range(15):
            metrics.record_failure(f"event_{i}", f"error_{i}")

        m = metrics.get_metrics()
        assert m["total_failed"] == 15
        assert len(m["recent_failures"]) == 10  # maxlen=10
        # Verify most recent failures are kept
        assert m["recent_failures"][0]["type"] == "event_5"  # First 5 dropped
        assert m["recent_failures"][-1]["type"] == "event_14"  # Last one kept


class TestNullEventBus:
    """Test NullEventBus error handling."""

    def test_publish_is_noop(self):
        """NullEventBus publish does nothing."""
        bus = NullEventBus()
        bus.publish("test_event", {"key": "value"})
        # Should not raise

    def test_broadcast_delegates_to_publish(self):
        """broadcast method delegates to publish."""
        bus = NullEventBus()
        bus.broadcast("test_event", {"key": "value"})
        # Should not raise

    def test_emit_delegates_to_publish(self):
        """emit method delegates to publish."""
        bus = NullEventBus()
        bus.emit("test_event", {"key": "value"})
        # Should not raise


class TestEventBusErrors:
    """Test error handling in event bus."""

    def test_publish_never_raises(self):
        """Publish must never raise, only log."""
        from app.core.events import RedisEventBus

        # Create a minimal mock that simulates failure
        class FailingRedisClient:
            def publish(self, channel, message):
                raise Exception("network error")

        bus = RedisEventBus.__new__(RedisEventBus)
        bus._sync_client = FailingRedisClient()
        bus._metrics = EventMetrics()

        # Should not raise despite Redis failure
        bus.publish("test_event", {"data": "test"})

        # Should have recorded failure
        metrics = bus._metrics.get_metrics()
        assert metrics["total_failed"] == 1
        assert len(metrics["recent_failures"]) == 1
        assert "network error" in metrics["recent_failures"][0]["error"]

    def test_event_metrics_capture_error_details(self):
        """Metrics capture the actual error message."""
        metrics = EventMetrics()
        error_msg = "Connection refused on 127.0.0.1:6379"
        metrics.record_failure("critical_event", error_msg)

        m = metrics.get_metrics()
        assert m["recent_failures"][0]["error"] == error_msg

    def test_get_event_metrics_with_null_bus(self):
        """get_event_metrics returns appropriate response for NullEventBus."""
        with patch('app.core.events._bus', NullEventBus()):
            metrics = get_event_metrics()
            assert metrics["bus_type"] == "NullEventBus"
            assert metrics["status"] == "metrics_unavailable"

    def test_multiple_errors_tracked_independently(self):
        """Different event types track failures independently."""
        metrics = EventMetrics()
        metrics.record_failure("build_started", "timeout")
        metrics.record_failure("evaluation_complete", "connection lost")
        metrics.record_success()

        m = metrics.get_metrics()
        assert m["total_published"] == 1
        assert m["total_failed"] == 2
        assert m["recent_failures"][0]["type"] == "build_started"
        assert m["recent_failures"][1]["type"] == "evaluation_complete"

