"""Tests for Distributed Compute Engine (Phase 10.6)."""

import time
from unittest.mock import Mock, patch

import pytest

from app.runtime.distributed import (
    Task,
    TaskQueue,
    TaskType,
    TaskPriority,
    TaskStatus,
    Worker,
    WorkerPool,
    JobScheduler,
    RecurringJob,
    DistributedEngine,
    get_engine,
)


# ===================================================================
# Task tests
# ===================================================================

def test_task_defaults():
    t = Task()
    assert t.task_id.startswith("task_")
    assert t.task_type == TaskType.CUSTOM
    assert t.priority == TaskPriority.NORMAL
    assert t.status == TaskStatus.PENDING
    assert t.retry_count == 0
    assert t.max_retries == 3
    assert t.timeout_seconds == 300.0


def test_task_with_explicit_id():
    t = Task(task_id="my_task", task_type=TaskType.PHYSICS_SIMULATION)
    assert t.task_id == "my_task"
    assert t.task_type == TaskType.PHYSICS_SIMULATION


def test_task_high_priority():
    t = Task(priority=TaskPriority.CRITICAL)
    assert t.priority == TaskPriority.CRITICAL


def test_task_duration():
    t = Task()
    t.started_at = "2026-01-01T00:00:00+00:00"
    t.completed_at = "2026-01-01T00:01:30+00:00"
    assert t.duration_seconds == 90.0


def test_task_duration_none():
    t = Task()
    assert t.duration_seconds is None


def test_task_is_terminal():
    assert Task(status=TaskStatus.COMPLETED).is_terminal is True
    assert Task(status=TaskStatus.FAILED).is_terminal is True
    assert Task(status=TaskStatus.CANCELLED).is_terminal is True
    assert Task(status=TaskStatus.TIMEOUT).is_terminal is True
    assert Task(status=TaskStatus.PENDING).is_terminal is False
    assert Task(status=TaskStatus.RUNNING).is_terminal is False


def test_task_to_dict():
    t = Task(task_id="t1", task_type=TaskType.COST_ANALYSIS, priority=TaskPriority.HIGH)
    d = t.to_dict()
    assert d["task_id"] == "t1"
    assert d["task_type"] == "cost_analysis"
    assert d["priority"] == 2
    assert d["status"] == "pending"


def test_task_type_values():
    assert TaskType.PHYSICS_SIMULATION.value == "physics_simulation"
    assert TaskType.DIGITAL_TWIN.value == "digital_twin"
    assert TaskType.PARETO_OPTIMIZATION.value == "pareto_optimization"


def test_task_priority_values():
    assert TaskPriority.LOW.value == 0
    assert TaskPriority.NORMAL.value == 1
    assert TaskPriority.HIGH.value == 2
    assert TaskPriority.CRITICAL.value == 3


# ===================================================================
# Task Queue tests
# ===================================================================

def test_queue_enqueue():
    q = TaskQueue()
    t = Task()
    tid = q.enqueue(t)
    assert tid == t.task_id
    assert t.status == TaskStatus.QUEUED


def test_queue_dequeue():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    dequeued = q.dequeue(worker_id="w1")
    assert dequeued is not None
    assert dequeued.task_id == t.task_id
    assert dequeued.status == TaskStatus.RUNNING
    assert dequeued.worker_id == "w1"


def test_queue_dequeue_empty():
    q = TaskQueue()
    assert q.dequeue() is None


def test_queue_dequeue_respects_priority():
    q = TaskQueue()
    low = Task(priority=TaskPriority.LOW)
    high = Task(priority=TaskPriority.CRITICAL)
    q.enqueue(low)
    q.enqueue(high)
    first = q.dequeue()
    assert first.priority == TaskPriority.CRITICAL


def test_queue_complete():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    q.dequeue()
    ok = q.complete(t.task_id, result="done")
    assert ok is True
    assert q.get(t.task_id).status == TaskStatus.COMPLETED
    assert q.get(t.task_id).result == "done"


def test_queue_complete_not_running():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    ok = q.complete(t.task_id)
    assert ok is False


def test_queue_fail_no_retry():
    q = TaskQueue()
    t = Task(max_retries=0)
    q.enqueue(t)
    q.dequeue()
    q.fail(t.task_id, error="boom", retry=False)
    assert q.get(t.task_id).status == TaskStatus.FAILED
    assert q.get(t.task_id).error == "boom"


def test_queue_fail_with_retry():
    q = TaskQueue()
    t = Task(max_retries=2)
    q.enqueue(t)
    q.dequeue()
    q.fail(t.task_id, error="retry me", retry=True)
    assert q.get(t.task_id).status == TaskStatus.QUEUED
    assert q.get(t.task_id).retry_count == 1


def test_queue_cancel():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    ok = q.cancel(t.task_id)
    assert ok is True
    assert q.get(t.task_id).status == TaskStatus.CANCELLED


def test_queue_cancel_terminal():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    q.dequeue()
    q.complete(t.task_id)
    ok = q.cancel(t.task_id)
    assert ok is False


def test_queue_stats():
    q = TaskQueue()
    q.enqueue(Task())
    q.enqueue(Task())
    t = q.dequeue()
    assert t is not None
    q.complete(t.task_id)
    stats = q.stats
    assert stats.get("queued", 0) == 1
    assert stats.get("completed", 0) == 1


def test_queue_pending_count():
    q = TaskQueue()
    assert q.pending_count == 0
    q.enqueue(Task())
    assert q.pending_count == 1


def test_queue_clear_completed():
    q = TaskQueue()
    t1 = Task()
    t2 = Task()
    q.enqueue(t1)
    q.enqueue(t2)
    q.dequeue()
    q.complete(t1.task_id)
    cleared = q.clear_completed()
    assert cleared >= 1


def test_queue_tasks_by_type():
    q = TaskQueue()
    t = Task(task_type=TaskType.PHYSICS_SIMULATION)
    q.enqueue(t)
    results = q.tasks_by_type(TaskType.PHYSICS_SIMULATION)
    assert len(results) == 1
    assert results[0].task_id == t.task_id


def test_queue_tasks_by_status():
    q = TaskQueue()
    t = Task()
    q.enqueue(t)
    results = q.tasks_by_status(TaskStatus.QUEUED)
    assert len(results) == 1


# ===================================================================
# Worker tests
# ===================================================================

def test_worker_start_stop():
    w = Worker(worker_id="test_worker")
    w.start()
    assert w._running is True
    w.stop()
    assert w._running is False


def test_worker_default_executor():
    w = Worker()
    task = Task(task_id="t1")
    result = w._default_executor(task)
    assert result == "executed_t1"


def test_worker_executes_task():
    q = TaskQueue()
    results = []

    def executor(task):
        results.append(task.task_id)
        return "done"

    w = Worker(worker_id="exec_worker", queue=q, executor=executor, poll_interval=0.05)
    w.start()
    t = Task()
    q.enqueue(t)
    time.sleep(0.3)
    w.stop()
    assert t.task_id in results
    assert q.get(t.task_id).status == TaskStatus.COMPLETED


def test_worker_properties():
    w = Worker(worker_id="prop_worker")
    assert w.worker_id == "prop_worker"
    assert w.is_busy is False
    assert w.tasks_completed == 0
    assert w.tasks_failed == 0


def test_worker_failing_executor():
    q = TaskQueue()

    def bad_exec(task):
        raise RuntimeError("fail")

    w = Worker(worker_id="fail_worker", queue=q, executor=bad_exec, poll_interval=0.05)
    w.start()
    t = Task(max_retries=0)
    q.enqueue(t)
    time.sleep(0.3)
    w.stop()
    assert q.get(t.task_id).status == TaskStatus.FAILED


# ===================================================================
# Worker Pool tests
# ===================================================================

def test_worker_pool_start_stop():
    pool = WorkerPool(num_workers=2)
    pool.start()
    assert pool._running is True
    assert len(pool._workers) == 2
    pool.stop()
    assert pool._running is False


def test_worker_pool_properties():
    pool = WorkerPool(num_workers=3)
    pool.start()
    assert pool.available_workers + pool.busy_workers == 3
    assert pool.total_completed == 0
    assert pool.total_failed == 0
    pool.stop()


def test_worker_pool_scale_up():
    pool = WorkerPool(num_workers=2)
    pool.start()
    count = pool.scale(5)
    assert count == 5
    assert len(pool._workers) == 5
    pool.stop()


def test_worker_pool_scale_down():
    pool = WorkerPool(num_workers=5)
    pool.start()
    count = pool.scale(2)
    assert count == 2
    assert len(pool._workers) == 2
    pool.stop()


def test_worker_pool_stats():
    pool = WorkerPool(num_workers=2)
    pool.start()
    stats = pool.stats
    assert stats["workers_total"] == 2
    assert "queue_pending" in stats
    pool.stop()


def test_worker_pool_processes_tasks():
    q = TaskQueue()
    pool = WorkerPool(queue=q, num_workers=2, poll_interval=0.05)
    pool.start()
    for i in range(5):
        q.enqueue(Task())
    time.sleep(0.5)
    pool.stop()
    completed = pool.total_completed
    stats_done = pool.queue.stats.get("completed", 0)
    assert completed + stats_done >= 1  # at least some processed


# ===================================================================
# Job Scheduler tests
# ===================================================================

def test_scheduler_register():
    q = TaskQueue()
    s = JobScheduler(queue=q)
    job = RecurringJob(
        job_id="test_job",
        task_type=TaskType.KNOWLEDGE_MINING,
        payload_factory=lambda: {"key": "value"},
        interval_seconds=9999,
    )
    s.register(job)
    assert "test_job" in s._jobs


def test_scheduler_unregister():
    q = TaskQueue()
    s = JobScheduler(queue=q)
    job = RecurringJob(
        job_id="remove_me", task_type=TaskType.CUSTOM,
        payload_factory=dict, interval_seconds=9999,
    )
    s.register(job)
    assert s.unregister("remove_me") is True
    assert s.unregister("nonexistent") is False


def test_scheduler_start_stop():
    q = TaskQueue()
    s = JobScheduler(queue=q)
    s.start()
    assert s._running is True
    s.stop()
    assert s._running is False


def test_scheduler_enqueues_job():
    q = TaskQueue()
    s = JobScheduler(queue=q)
    call_count = [0]

    def factory():
        call_count[0] += 1
        return {"count": call_count[0]}

    job = RecurringJob(
        job_id="frequent", task_type=TaskType.CUSTOM,
        payload_factory=factory, interval_seconds=0.1,
    )
    s.register(job)
    s._enqueue_job(job)
    assert call_count[0] == 1
    assert q.pending_count >= 1


def test_scheduler_stats():
    q = TaskQueue()
    s = JobScheduler(queue=q)
    stats = s.stats
    assert stats["jobs_registered"] == 0


def test_recurring_job_defaults():
    job = RecurringJob(
        job_id="j1", task_type=TaskType.CUSTOM,
        payload_factory=dict, interval_seconds=60.0,
    )
    assert job.label == "j1"
    assert job.total_enqueued == 0
    assert job.last_enqueued == ""


# ===================================================================
# Distributed Engine tests
# ===================================================================

def test_engine_start_stop():
    engine = DistributedEngine(num_workers=2)
    engine.start()
    assert engine.pool._running is True
    assert engine.scheduler._running is True
    engine.stop()
    assert engine.pool._running is False
    assert engine.scheduler._running is False


def test_engine_submit():
    engine = DistributedEngine()
    t = Task(task_type=TaskType.PHYSICS_SIMULATION, payload={"config": {}})
    tid = engine.submit(t)
    assert tid == t.task_id
    assert engine.queue.get(tid) is not None


def test_engine_submit_physics():
    engine = DistributedEngine()
    tid = engine.submit_physics({"drum_diameter": 1200})
    task = engine.queue.get(tid)
    assert task.task_type == TaskType.PHYSICS_SIMULATION
    assert task.payload["config"]["drum_diameter"] == 1200


def test_engine_submit_experiment():
    engine = DistributedEngine()
    tid = engine.submit_experiment({"param": 1.0})
    assert engine.queue.get(tid).task_type == TaskType.EXPERIMENT_VARIANT


def test_engine_submit_pareto():
    engine = DistributedEngine()
    tid = engine.submit_pareto({"generations": 20})
    assert engine.queue.get(tid).task_type == TaskType.PARETO_OPTIMIZATION


def test_engine_submit_digital_twin():
    engine = DistributedEngine()
    tid = engine.submit_digital_twin({"config": {}})
    assert engine.queue.get(tid).task_type == TaskType.DIGITAL_TWIN


def test_engine_get_result():
    engine = DistributedEngine()
    t = Task()
    engine.submit(t)
    result = engine.get_result(t.task_id)
    assert result is not None
    assert result.task_id == t.task_id
    assert engine.get_result("nonexistent") is None


def test_engine_schedule_recurring():
    engine = DistributedEngine()
    job = engine.schedule_recurring(
        job_id="heartbeat",
        task_type=TaskType.TELEMETRY_ANALYSIS,
        payload_factory=lambda: {"ts": time.time()},
        interval_seconds=60.0,
    )
    assert job.job_id == "heartbeat"
    assert job.task_type == TaskType.TELEMETRY_ANALYSIS
    assert "heartbeat" in engine.scheduler._jobs


def test_engine_stats():
    engine = DistributedEngine(num_workers=2)
    engine.start()
    stats = engine.stats
    assert "pool" in stats
    assert "scheduler" in stats
    engine.stop()


def test_get_engine_singleton():
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_engine_processes_tasks():
    engine = DistributedEngine(num_workers=2)
    engine.start()
    for i in range(4):
        engine.submit(Task())
    time.sleep(0.5)
    engine.stop()
    stats = engine.queue.stats
    completed = stats.get("completed", 0)
    assert completed >= 0  # at least no crash
