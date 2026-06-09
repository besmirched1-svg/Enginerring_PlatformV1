"""Distributed Compute Engine — task queues, worker pools, job scheduling.

Phase 10.6: allows engineering workloads to scale horizontally across
multiple workers, machines, or containers.

Architecture:
  Task -> TaskQueue -> WorkerPool (N Workers) -> Result

  JobScheduler periodically enqueues recurring work.
"""

import enum
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("engine.runtime.compute")

# ---------------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    PHYSICS_SIMULATION = "physics_simulation"
    DIGITAL_TWIN = "digital_twin"
    EXPERIMENT_VARIANT = "experiment_variant"
    PARETO_OPTIMIZATION = "pareto_optimization"
    MANUFACTURING_EVAL = "manufacturing_eval"
    COST_ANALYSIS = "cost_analysis"
    CAD_GENERATION = "cad_generation"
    COMMITTEE_SESSION = "committee_session"
    KNOWLEDGE_MINING = "knowledge_mining"
    TELEMETRY_ANALYSIS = "telemetry_analysis"
    CUSTOM = "custom"


class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------

@dataclass
class Task:
    task_id: str = ""
    task_type: TaskType = TaskType.CUSTOM
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    result: Any = None
    error: str = ""
    worker_id: str = ""
    timeout_seconds: float = 300.0
    retry_count: int = 0
    max_retries: int = 3
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"task_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.status:
            self.status = TaskStatus.PENDING

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.started_at or not self.completed_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED, TaskStatus.FAILED,
            TaskStatus.CANCELLED, TaskStatus.TIMEOUT,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "worker_id": self.worker_id,
            "retry_count": self.retry_count,
            "duration_seconds": self.duration_seconds,
        }


# ---------------------------------------------------------------------------
# Task Queue
# ---------------------------------------------------------------------------

class TaskQueue:
    """Priority-based task queue with status tracking."""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._pending: Dict[int, List[str]] = defaultdict(list)
        self._lock = threading.Lock()

    def enqueue(self, task: Task) -> str:
        with self._lock:
            task.status = TaskStatus.QUEUED
            self._tasks[task.task_id] = task
            self._pending[task.priority.value].append(task.task_id)
        logger.debug("Task queued: %s (%s)", task.task_id, task.task_type.value)
        return task.task_id

    def dequeue(self, worker_id: str = "") -> Optional[Task]:
        with self._lock:
            for priority in sorted(self._pending.keys(), reverse=True):
                queue = self._pending[priority]
                while queue:
                    task_id = queue.pop(0)
                    task = self._tasks.get(task_id)
                    if task and task.status == TaskStatus.QUEUED:
                        task.status = TaskStatus.RUNNING
                        task.started_at = datetime.now(timezone.utc).isoformat()
                        task.worker_id = worker_id
                        logger.info("Task dequeued: %s (worker=%s)", task_id, worker_id)
                        return task
        return None

    def complete(self, task_id: str, result: Any = None) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return False
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.result = result
        logger.info("Task completed: %s", task_id)
        return True

    def fail(self, task_id: str, error: str = "", retry: bool = True) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if retry and task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.QUEUED
                task.error = error
                self._pending[task.priority.value].append(task.task_id)
                logger.info("Task re-queued: %s (retry %d/%d)",
                            task_id, task.retry_count, task.max_retries)
                return True
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.error = error
        logger.warning("Task failed: %s — %s", task_id, error)
        return True

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.is_terminal:
                return False
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc).isoformat()
        logger.info("Task cancelled: %s", task_id)
        return True

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    @property
    def stats(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for t in self._tasks.values():
            counts[t.status.value] += 1
        return dict(counts)

    @property
    def pending_count(self) -> int:
        return sum(len(q) for q in self._pending.values())

    @property
    def all_tasks(self) -> List[Task]:
        return list(self._tasks.values())

    def tasks_by_type(self, task_type: TaskType) -> List[Task]:
        return [t for t in self._tasks.values() if t.task_type == task_type]

    def tasks_by_status(self, status: TaskStatus) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == status]

    def clear_completed(self) -> int:
        with self._lock:
            ids = [tid for tid, t in self._tasks.items() if t.is_terminal]
            for tid in ids:
                del self._tasks[tid]
        return len(ids)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class Worker:
    """A single worker that pulls tasks from a queue and executes them."""

    def __init__(
        self,
        worker_id: str = "",
        queue: Optional[TaskQueue] = None,
        executor: Optional[Callable[[Task], Any]] = None,
        poll_interval: float = 1.0,
    ):
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self._queue = queue or TaskQueue()
        self._executor = executor or self._default_executor
        self._poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._current_task: Optional[Task] = None

    # -- Properties --

    @property
    def is_busy(self) -> bool:
        return self._current_task is not None

    @property
    def tasks_completed(self) -> int:
        return self._tasks_completed

    @property
    def tasks_failed(self) -> int:
        return self._tasks_failed

    @property
    def current_task_id(self) -> str:
        return self._current_task.task_id if self._current_task else ""

    # -- Lifecycle --

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        logger.info("Worker started: %s", self.worker_id)

    def stop(self) -> None:
        self._running = False
        logger.info("Worker stopped: %s (completed=%d, failed=%d)",
                     self.worker_id, self._tasks_completed, self._tasks_failed)

    # -- Execution --

    def _worker_loop(self) -> None:
        while self._running:
            task = self._queue.dequeue(worker_id=self.worker_id)
            if task:
                self._execute(task)
            else:
                time.sleep(self._poll_interval)

    def _execute(self, task: Task) -> None:
        self._current_task = task
        logger.info("Worker %s executing task %s (%s)",
                     self.worker_id, task.task_id, task.task_type.value)
        try:
            result = self._executor(task)
            self._queue.complete(task.task_id, result)
            self._tasks_completed += 1
            self._current_task = None
        except Exception as exc:
            error = str(exc)
            logger.error("Worker %s task %s failed: %s",
                         self.worker_id, task.task_id, error)
            retry = task.retry_count < task.max_retries
            self._queue.fail(task.task_id, error=error, retry=retry)
            self._tasks_failed += 1
            self._current_task = None

    @staticmethod
    def _default_executor(task: Task) -> str:
        logger.info("Executing task %s (%s)", task.task_id, task.task_type.value)
        time.sleep(0.1)
        return f"executed_{task.task_id}"


# ---------------------------------------------------------------------------
# Worker Pool
# ---------------------------------------------------------------------------

class WorkerPool:
    """Manages a pool of worker threads."""

    def __init__(
        self,
        queue: Optional[TaskQueue] = None,
        num_workers: int = 4,
        executor: Optional[Callable[[Task], Any]] = None,
        poll_interval: float = 1.0,
    ):
        self._queue = queue or TaskQueue()
        self._num_workers = num_workers
        self._executor = executor
        self._poll_interval = poll_interval
        self._workers: List[Worker] = []
        self._running = False

    @property
    def queue(self) -> TaskQueue:
        return self._queue

    @property
    def available_workers(self) -> int:
        return sum(1 for w in self._workers if not w.is_busy)

    @property
    def busy_workers(self) -> int:
        return sum(1 for w in self._workers if w.is_busy)

    @property
    def total_completed(self) -> int:
        return sum(w.tasks_completed for w in self._workers)

    @property
    def total_failed(self) -> int:
        return sum(w.tasks_failed for w in self._workers)

    def start(self, num_workers: Optional[int] = None) -> None:
        if self._running:
            return
        self._running = True
        count = num_workers or self._num_workers
        self._workers = [
            Worker(
                worker_id=f"worker_{i}",
                queue=self._queue,
                executor=self._executor,
                poll_interval=self._poll_interval,
            )
            for i in range(count)
        ]
        for w in self._workers:
            w.start()
        logger.info("Worker pool started: %d workers", count)

    def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.stop()
        logger.info("Worker pool stopped")

    def scale(self, target: int) -> int:
        current = len(self._workers)
        if target > current:
            for i in range(current, target):
                w = Worker(
                    worker_id=f"worker_{i}",
                    queue=self._queue,
                    executor=self._executor,
                )
                w.start()
                self._workers.append(w)
            logger.info("Worker pool scaled up: %d -> %d", current, target)
        elif target < current:
            for w in self._workers[target:]:
                w.stop()
            self._workers = self._workers[:target]
            logger.info("Worker pool scaled down: %d -> %d", current, target)
        return len(self._workers)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "workers_total": len(self._workers),
            "workers_available": self.available_workers,
            "workers_busy": self.busy_workers,
            "tasks_completed": self.total_completed,
            "tasks_failed": self.total_failed,
            "queue_pending": self._queue.pending_count,
            "queue_stats": self._queue.stats,
        }


# ---------------------------------------------------------------------------
# Job Scheduler
# ---------------------------------------------------------------------------

class RecurringJob:
    """A job that runs on a schedule."""

    def __init__(
        self,
        job_id: str,
        task_type: TaskType,
        payload_factory: Callable[[], Dict[str, Any]],
        interval_seconds: float,
        priority: TaskPriority = TaskPriority.NORMAL,
        label: str = "",
    ):
        self.job_id = job_id
        self.task_type = task_type
        self.payload_factory = payload_factory
        self.interval = interval_seconds
        self.priority = priority
        self.label = label or job_id
        self.last_enqueued: str = ""
        self.total_enqueued: int = 0


class JobScheduler:
    """Schedules recurring engineering jobs."""

    def __init__(self, queue: TaskQueue):
        self._queue = queue
        self._jobs: Dict[str, RecurringJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register(self, job: RecurringJob) -> None:
        self._jobs[job.job_id] = job
        logger.info("Scheduled job: %s (every %ss)", job.job_id, job.interval)

    def unregister(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info("Job scheduler started (%d jobs)", len(self._jobs))

    def stop(self) -> None:
        self._running = False
        logger.info("Job scheduler stopped")

    def _scheduler_loop(self) -> None:
        last_tick: Dict[str, float] = {}
        while self._running:
            now = time.time()
            for job in self._jobs.values():
                last = last_tick.get(job.job_id, 0.0)
                if now - last >= job.interval:
                    self._enqueue_job(job)
                    last_tick[job.job_id] = now
            time.sleep(1.0)

    def _enqueue_job(self, job: RecurringJob) -> None:
        try:
            payload = job.payload_factory()
        except Exception as exc:
            logger.error("Job %s payload factory failed: %s", job.job_id, exc)
            return

        task = Task(
            task_type=job.task_type,
            payload=payload,
            priority=job.priority,
            tags={"job_id": job.job_id, "label": job.label},
        )
        self._queue.enqueue(task)
        job.last_enqueued = datetime.now(timezone.utc).isoformat()
        job.total_enqueued += 1
        logger.debug("Job %s enqueued task %s", job.job_id, task.task_id)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "jobs_registered": len(self._jobs),
            "jobs": [
                {
                    "job_id": j.job_id,
                    "task_type": j.task_type.value,
                    "interval": j.interval,
                    "total_enqueued": j.total_enqueued,
                    "last_enqueued": j.last_enqueued,
                }
                for j in self._jobs.values()
            ],
        }


# ---------------------------------------------------------------------------
# Distributed Engine — top-level coordinator
# ---------------------------------------------------------------------------

class DistributedEngine:
    """Top-level distributed compute coordinator.

    Manages task queue, worker pool, and job scheduler together.
    """

    def __init__(self, num_workers: int = 4, executor: Optional[Callable] = None):
        self.queue = TaskQueue()
        self.pool = WorkerPool(
            queue=self.queue,
            num_workers=num_workers,
            executor=executor,
        )
        self.scheduler = JobScheduler(queue=self.queue)

    def start(self) -> None:
        self.pool.start()
        self.scheduler.start()
        logger.info("Distributed engine started (%d workers)", len(self.pool._workers))

    def stop(self) -> None:
        self.scheduler.stop()
        self.pool.stop()
        logger.info("Distributed engine stopped")

    def submit(self, task: Task) -> str:
        return self.queue.enqueue(task)

    def submit_physics(self, config: Dict[str, Any], priority: TaskPriority = TaskPriority.NORMAL) -> str:
        return self.queue.enqueue(Task(
            task_type=TaskType.PHYSICS_SIMULATION,
            payload={"config": config},
            priority=priority,
        ))

    def submit_experiment(self, config: Dict[str, Any], priority: TaskPriority = TaskPriority.NORMAL) -> str:
        return self.queue.enqueue(Task(
            task_type=TaskType.EXPERIMENT_VARIANT,
            payload={"config": config},
            priority=priority,
        ))

    def submit_pareto(self, params: Dict[str, Any], priority: TaskPriority = TaskPriority.NORMAL) -> str:
        return self.queue.enqueue(Task(
            task_type=TaskType.PARETO_OPTIMIZATION,
            payload=params,
            priority=priority,
        ))

    def submit_digital_twin(self, config: Dict[str, Any]) -> str:
        return self.queue.enqueue(Task(
            task_type=TaskType.DIGITAL_TWIN,
            payload={"config": config},
        ))

    def get_result(self, task_id: str) -> Optional[Task]:
        return self.queue.get(task_id)

    def schedule_recurring(
        self,
        job_id: str,
        task_type: TaskType,
        payload_factory: Callable[[], Dict],
        interval_seconds: float,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> RecurringJob:
        job = RecurringJob(
            job_id=job_id,
            task_type=task_type,
            payload_factory=payload_factory,
            interval_seconds=interval_seconds,
            priority=priority,
        )
        self.scheduler.register(job)
        return job

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "pool": self.pool.stats,
            "scheduler": self.scheduler.stats,
        }


_daemon_engine: Optional[DistributedEngine] = None


def get_engine(num_workers: int = 4) -> DistributedEngine:
    global _daemon_engine
    if _daemon_engine is None:
        _daemon_engine = DistributedEngine(num_workers=num_workers)
    return _daemon_engine
