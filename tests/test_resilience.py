import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from app.core.resilience import exponential_backoff_retry, RedisHeartbeat


class TestExponentialBackoffRetry:
    """Test exponential backoff retry decorator."""

    def test_successful_call_first_attempt(self):
        """Successful operation on first attempt returns immediately."""
        mock_func = Mock(return_value="success")
        decorated = exponential_backoff_retry(max_attempts=3)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_exception(self):
        """Function retries on specified exceptions."""
        mock_func = Mock(side_effect=[Exception("fail1"), Exception("fail2"), "success"])
        decorated = exponential_backoff_retry(
            max_attempts=3,
            initial_delay=0.01,
            exceptions=(Exception,)
        )(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 3

    def test_max_attempts_exceeded(self):
        """Raises exception after max attempts exceeded."""
        mock_func = Mock(side_effect=Exception("persistent error"))
        decorated = exponential_backoff_retry(
            max_attempts=3,
            initial_delay=0.01,
            exceptions=(Exception,)
        )(mock_func)

        with pytest.raises(Exception, match="persistent error"):
            decorated()

        assert mock_func.call_count == 3

    def test_exponential_backoff_timing(self):
        """Retry delays increase exponentially."""
        start_times = []

        def failing_func():
            start_times.append(time.time())
            if len(start_times) < 3:
                raise Exception("fail")
            return "success"

        decorated = exponential_backoff_retry(
            max_attempts=3,
            initial_delay=0.02,
            jitter=False
        )(failing_func)

        result = decorated()

        assert result == "success"
        # Check that delays increased (approximately exponential)
        if len(start_times) >= 3:
            delay1 = start_times[1] - start_times[0]
            delay2 = start_times[2] - start_times[1]
            assert delay2 > delay1  # Second delay should be longer

    def test_jitter_enabled(self):
        """Jitter adds randomness to delays."""
        call_times = []

        def failing_func():
            call_times.append(time.time())
            if len(call_times) < 2:
                raise Exception("fail")
            return "success"

        decorated = exponential_backoff_retry(
            max_attempts=2,
            initial_delay=0.05,
            jitter=True
        )(failing_func)

        result = decorated()

        assert result == "success"
        assert len(call_times) == 2


class TestRedisHeartbeat:
    """Test Redis heartbeat monitoring."""

    def test_healthy_redis(self):
        """Heartbeat returns True when Redis is healthy."""
        mock_redis = Mock()
        mock_redis.ping.return_value = True

        heartbeat = RedisHeartbeat(mock_redis, check_interval=0.1)
        health = heartbeat.check_health()

        assert health is True
        assert heartbeat.is_healthy is True
        assert heartbeat.consecutive_failures == 0

    def test_unhealthy_redis_after_failures(self):
        """Heartbeat marks Redis unhealthy after 3 failures."""
        mock_redis = Mock()
        mock_redis.ping.side_effect = Exception("connection failed")

        heartbeat = RedisHeartbeat(mock_redis, check_interval=0.01)

        # First two failures
        assert heartbeat.check_health() is False
        assert heartbeat.is_healthy is True  # Still considered healthy

        time.sleep(0.02)  # Bypass interval check
        assert heartbeat.check_health() is False

        time.sleep(0.02)  # Bypass interval check
        result = heartbeat.check_health()

        # After 3 failures, should be marked unhealthy
        assert result is False
        assert heartbeat.is_healthy is False
        assert heartbeat.consecutive_failures == 3

    def test_check_interval_respected(self):
        """Heartbeat skips checks within interval."""
        mock_redis = Mock()
        mock_redis.ping.return_value = True

        heartbeat = RedisHeartbeat(mock_redis, check_interval=1.0)

        # First check
        heartbeat.check_health()
        call_count_1 = mock_redis.ping.call_count

        # Second check immediately (within interval)
        heartbeat.check_health()
        call_count_2 = mock_redis.ping.call_count

        # Should not have called ping again
        assert call_count_1 == call_count_2 == 1

    def test_recovery_resets_failures(self):
        """Recovery resets consecutive failure counter."""
        mock_redis = Mock()
        mock_redis.ping.side_effect = [
            Exception("fail"),
            Exception("fail"),
            True,  # Recovery
        ]

        heartbeat = RedisHeartbeat(mock_redis, check_interval=0.01)

        heartbeat.check_health()
        time.sleep(0.02)
        heartbeat.check_health()
        assert heartbeat.consecutive_failures == 2

        time.sleep(0.02)
        heartbeat.check_health()

        assert heartbeat.consecutive_failures == 0
        assert heartbeat.is_healthy is True

    def test_wait_for_recovery_success(self):
        """wait_for_recovery returns True when Redis recovers."""
        mock_redis = Mock()
        call_count = [0]

        def ping_side_effect():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("fail")
            return True

        mock_redis.ping.side_effect = ping_side_effect

        heartbeat = RedisHeartbeat(mock_redis, check_interval=0.01)
        heartbeat.is_healthy = False

        result = heartbeat.wait_for_recovery(max_wait=5.0)

        assert result is True
        assert heartbeat.is_healthy is True

    def test_wait_for_recovery_timeout(self):
        """wait_for_recovery returns False on timeout."""
        mock_redis = Mock()
        mock_redis.ping.side_effect = Exception("persistent failure")

        heartbeat = RedisHeartbeat(mock_redis, check_interval=0.01)

        result = heartbeat.wait_for_recovery(max_wait=0.05)

        assert result is False
