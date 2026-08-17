"""任务控制面：审核 / 暂停 / 恢复 / 取消 / 重试（从 WorkflowService 拆出）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from blog_writer.workflow import helpers as wf_helpers
from blog_writer.workflow import review_wait as review_wait_mod
from blog_writer.review_event_bus import publish_review_decision_sync

logger = logging.getLogger(__name__)


class TaskControlMixin:
    """依赖 WorkflowService 的状态/锁/调度方法（duck-typed）。"""

    def get_pending_reviews(self) -> List[Dict[str, Any]]:
        reviews = []
        seen = set()

        def _append(task_id: str, task: Dict[str, Any]):
            if task_id in seen:
                return
            if task.get("status") != "waiting_review":
                return
            seen.add(task_id)
            reviews.append({
                "task_id": task_id,
                "node_id": task.get("review_node", ""),
                "node_name": task.get("review_node_name", ""),
                "keywords": task.get("keywords", ""),
                "mode": task.get("mode", ""),
            })

        for task_id, task in self._tasks.items():
            _append(task_id, task)

        if self._use_db:
            try:
                for db_task in self._task_repo.list_tasks(status="waiting_review", limit=200):
                    tid = db_task.get("task_id", "")
                    if tid and tid not in self._tasks:
                        self._tasks[tid] = db_task
                    _append(tid, db_task)
            except Exception as e:
                logger.warning(f"从数据库加载待审任务失败: {e}")
        return reviews

    def approve_review(
        self,
        task_id: str,
        decision: str,
        modifications: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._get_task_sync_lock(task_id):
            task = self._ensure_task_loaded(task_id)
            if not task or task["status"] != "waiting_review":
                return False

            existing = task.get("review_decision")
            if existing:
                if existing == decision and (modifications or {}) == (
                    task.get("review_modifications") or {}
                ):
                    _ev = self._pause_events.get(task_id)
                    if _ev is not None:
                        _ev.set()
                    review_wait_mod.publish_review_decision(
                        task_id, decision, modifications or {}
                    )
                    publish_review_decision_sync(task_id, decision, modifications)
                    return True
                logger.warning(
                    "task %s already has review_decision=%s, reject overwrite with %s",
                    task_id,
                    existing,
                    decision,
                )
                return False

            task["review_decision"] = decision
            task["review_modifications"] = modifications or {}
            review_wait_mod.publish_review_decision(
                task_id, decision, modifications or {}
            )
            publish_review_decision_sync(task_id, decision, modifications)

            _ev = self._pause_events.get(task_id)
            if _ev is not None:
                _ev.set()
                self._save_state(task_id)
                return True

            self._save_state(task_id)
            scheduled = self._schedule_resume_from_current(task_id, task)
            if not scheduled:
                logger.warning(
                    "review decision accepted but resume not scheduled for %s",
                    task_id,
                )
            return True

    def pause_task(self, task_id: str) -> bool:
        with self._get_task_sync_lock(task_id):
            task = self._ensure_task_loaded(task_id)
            if task and task["status"] in ("running", "waiting_review"):
                task["_prev_status"] = task["status"]
                task["status"] = "paused"
                self._save_state(task_id)
                self._fire_task_webhook(task_id, "task.paused", {"task_id": task_id})
                return True
            return False

    def resume_task(self, task_id: str) -> bool:
        with self._get_task_sync_lock(task_id):
            task = self._ensure_task_loaded(task_id)
            if not task or task["status"] != "paused":
                return False

            # 恢复到暂停前的状态（running 或 waiting_review）
            prev_status = task.get("_prev_status", "running")
            if prev_status not in ("running", "waiting_review"):
                prev_status = "running"

            # 如果执行循环仍在运行（等待当前步骤完成），只需改回状态
            if self.is_task_executing(task_id):
                logger.info("task %s still executing, resume by changing status to %s", task_id, prev_status)
                task["status"] = prev_status
                _ev = self._pause_events.get(task_id)
                if _ev is not None:
                    _ev.set()
                self._save_state(task_id)
                self._fire_task_webhook(task_id, "task.resumed", {"task_id": task_id})
                return True

            task["status"] = prev_status
            _ev = self._pause_events.get(task_id)
            if _ev is not None:
                _ev.set()
            self._save_state(task_id)
            self._fire_task_webhook(task_id, "task.resumed", {"task_id": task_id})

            step_files = task.get("step_files", [])
            current_step = task.get("current_step", 0)

            if not step_files or current_step >= len(step_files):
                return True

            remaining = step_files[current_step:]
            completed = set(task.get("completed_steps", []))
            if remaining and all(s in completed for s in remaining):
                task["status"] = "completed"
                self._save_state(task_id)
                if hasattr(self, "_schedule_task_memory_cleanup"):
                    self._schedule_task_memory_cleanup(task_id)
                return True

            return self._schedule_resume_from_current(task_id, task)

    def cancel_task(self, task_id: str) -> bool:
        with self._get_task_sync_lock(task_id):
            task = self._ensure_task_loaded(task_id)
            if not task:
                return False
            was_waiting_review = task.get("status") == "waiting_review"
            task["status"] = "cancelled"
            if was_waiting_review:
                task["review_decision"] = "reject"
                review_wait_mod.publish_review_decision(task_id, "reject", {})
                _ev = self._pause_events.get(task_id)
                if _ev is not None:
                    _ev.set()
            self._save_state(task_id)
            self._fire_task_webhook(task_id, "task.cancelled", {"task_id": task_id})
            if hasattr(self, "_schedule_task_memory_cleanup"):
                self._schedule_task_memory_cleanup(task_id)
            return True

    def retry_node(self, task_id: str, node_file: str) -> bool:
        """重试指定节点并自动调度续跑。"""
        with self._get_task_sync_lock(task_id):
            task = self._ensure_task_loaded(task_id)
            if not task:
                return False

            step_files = task.get("step_files", [])
            if node_file not in step_files:
                return False

            # 清除残留的审核决策，防止 _await_human_review 误用旧决策
            task.pop("review_decision", None)
            task.pop("review_modifications", None)
            task.pop("review_node", None)
            task.pop("review_node_name", None)

            completed = task.get("completed_steps", [])
            task["completed_steps"] = [s for s in completed if s != node_file]

            results = task.get("results", [])
            task["results"] = [r for r in results if r.get("step") != node_file]

            retry_counts = task.get("retry_counts", {})
            retry_counts[node_file] = retry_counts.get(node_file, 0) + 1
            task["retry_counts"] = retry_counts

            outputs = dict(task.get("outputs") or {})
            task["outputs"] = wf_helpers.prune_outputs_for_steps(
                outputs, {node_file}, self.load_node_definition
            )

            if task.get("status") in (
                "completed",
                "failed",
                "completed_partial",
                "rejected",
            ):
                task["status"] = "running"

            task["current_step"] = step_files.index(node_file)

            self._save_state(task_id)

            if not self.is_task_executing(task_id):
                return self._schedule_resume_from_current(task_id, task)
            return True
