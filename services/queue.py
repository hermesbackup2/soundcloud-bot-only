"""asyncio-based download queue with worker pool."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class QueueTask:
    task_id: int
    user_id: int
    urls: list
    chat_id: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    completed: int = 0
    failed: int = 0
    total: int = 0
    status: str = "pending"
    cancel_requested: bool = False

    def __post_init__(self):
        self.total = len(self.urls)


class DownloadQueue:
    def __init__(self, num_workers: int = 2):
        self.num_workers = num_workers
        self.queue: asyncio.Queue = asyncio.Queue()
        self.tasks: dict = {}
        self.user_tasks: dict = {}
        self._next_id = 1
        self._workers: list = []
        self._processor: Optional[Callable] = None
        self._running = False

    def set_processor(self, processor: Callable):
        self._processor = processor

    async def start(self):
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.num_workers)
        ]
        logger.info(f"Download queue started with {self.num_workers} workers")

    async def stop(self):
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def _worker(self, worker_id: int):
        while self._running:
            try:
                task = await self.queue.get()
                if task.cancel_requested:
                    task.status = "cancelled"
                    self.queue.task_done()
                    continue
                task.status = "running"
                task.started_at = datetime.utcnow()
                logger.info(f"[worker {worker_id}] Starting task {task.task_id}")
                try:
                    if self._processor:
                        await self._processor(task)
                    task.status = "done"
                except Exception:
                    logger.exception(f"[worker {worker_id}] Task failed")
                    task.status = "done"
                finally:
                    task.finished_at = datetime.utcnow()
                    if self.user_tasks.get(task.user_id) == task.task_id:
                        self.user_tasks.pop(task.user_id, None)
                    self.queue.task_done()
                    logger.info(
                        f"[worker {worker_id}] Finished task {task.task_id} "
                        f"({task.completed}/{task.total} ok)"
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"[worker {worker_id}] Unexpected error")

    async def enqueue(self, user_id, urls, chat_id):
        if user_id in self.user_tasks:
            existing_id = self.user_tasks[user_id]
            existing = self.tasks.get(existing_id)
            if existing and existing.status in ("pending", "running"):
                return None
        task_id = self._next_id
        self._next_id += 1
        task = QueueTask(task_id=task_id, user_id=user_id, urls=urls, chat_id=chat_id)
        self.tasks[task_id] = task
        self.user_tasks[user_id] = task_id
        await self.queue.put(task)
        logger.info(f"Task {task_id} enqueued for user {user_id} ({len(urls)} urls)")
        return task_id

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def get_user_task(self, user_id):
        tid = self.user_tasks.get(user_id)
        return self.tasks.get(tid) if tid else None

    def cancel(self, user_id):
        task = self.get_user_task(user_id)
        if not task:
            return False
        task.cancel_requested = True
        if task.status == "pending":
            task.status = "cancelled"
        return True

    def queue_position(self, user_id):
        task = self.get_user_task(user_id)
        if not task or task.status != "pending":
            return None
        pos = 0
        for t in self.tasks.values():
            if t.status == "pending" and t.task_id < task.task_id:
                pos += 1
        return pos

    def size(self):
        return self.queue.qsize()

    def stats(self):
        by_status = {}
        for t in self.tasks.values():
            by_status[t.status] = by_status.get(t.status, 0) + 1
        return {
            "queue_size": self.size(),
            "workers": self.num_workers,
            "by_status": by_status,
        }


download_queue = DownloadQueue(num_workers=2)
