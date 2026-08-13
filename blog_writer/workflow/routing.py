"""基于 registry.json routing 的工作流导航。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """下一步路由决策。"""

    next_node_id: Optional[str]
    next_step_file: Optional[str]
    action: str  # continue | jump | finish | fail_closed
    reason: str = ""


class WorkflowRouter:
    """解析 registry.routing，将 node_id 映射到 step 文件并计算下一跳。"""

    def __init__(
        self,
        registry: Dict[str, Any],
        step_files: List[str],
        load_node: Callable[[str], Dict[str, Any]],
    ):
        self.registry = registry or {}
        self.routing: Dict[str, Any] = self.registry.get("routing") or {}
        self.step_files = list(step_files)
        self._load_node = load_node
        self.id_to_file: Dict[str, str] = {}
        self.file_to_id: Dict[str, str] = {}
        self._build_maps()

    def _build_maps(self) -> None:
        for step_file in self.step_files:
            try:
                node = self._load_node(step_file)
            except FileNotFoundError:
                logger.warning("routing: node file missing: %s", step_file)
                continue
            node_id = node.get("id") or ""
            if not node_id:
                continue
            self.id_to_file[node_id] = step_file
            self.file_to_id[step_file] = node_id

    def node_id_for_file(self, step_file: str) -> str:
        return self.file_to_id.get(step_file, "")

    def file_for_node_id(self, node_id: str) -> Optional[str]:
        if not node_id:
            return None
        return self.id_to_file.get(node_id)

    def route_config(self, node_id: str) -> Dict[str, Any]:
        return dict(self.routing.get(node_id) or {})

    def max_retries_for(self, node_id: str, default: int = 3) -> int:
        cfg = self.route_config(node_id)
        if "max_retries" in cfg:
            try:
                return int(cfg["max_retries"])
            except (TypeError, ValueError):
                return default
        return default

    def _resolve_override(
        self,
        node_id: str,
        mode: str,
        risk_code: Optional[str],
        default_target: Optional[str],
        *,
        allow_risk: bool = True,
    ) -> Optional[str]:
        """统一 mode_override / risk_based 覆盖（保持与历史 resolve_next 一致）。

        优先级（passed 路径）：
        1. mode_override[mode] 为非空字符串 → 覆盖
        2. mode_override[mode] 为 null → 保留 default_target（通常为 on_pass）
        3. allow_risk 且非 manual 时，risk_based[risk_code] 字符串可再次覆盖
        """
        cfg = self.route_config(node_id)
        override = cfg.get("mode_override") or {}
        target = default_target

        if mode in override:
            ov = override[mode]
            if isinstance(ov, str) and ov:
                target = ov
            # ov is None → 保留 default_target

        if allow_risk and mode != "manual":
            risk_map = override.get("risk_based") or {}
            if risk_code and risk_code in risk_map and isinstance(risk_map[risk_code], str):
                target = risk_map[risk_code]

        return target

    def resolve_next(
        self,
        node_id: str,
        *,
        passed: bool,
        mode: str = "auto",
        risk_code: Optional[str] = None,
        linear_fallback: bool = True,
    ) -> RouteDecision:
        """根据通过/失败计算下一节点。"""
        cfg = self.route_config(node_id)

        if not cfg:
            # 无 routing 条目：线性下一文件
            return self._linear_next(node_id, passed=passed, linear_fallback=linear_fallback)

        key = "on_pass" if passed else "on_fail"
        target_id = cfg.get(key)
        if isinstance(target_id, str):
            target_id = target_id.strip() or None
        else:
            target_id = None

        if passed:
            target_id = self._resolve_override(
                node_id,
                mode,
                risk_code,
                target_id,
                allow_risk=True,
            )

        if not target_id:
            if passed:
                return RouteDecision(
                    next_node_id=None,
                    next_step_file=None,
                    action="finish",
                    reason="empty on_pass",
                )
            return RouteDecision(
                next_node_id=None,
                next_step_file=None,
                action="fail_closed",
                reason="empty on_fail",
            )

        step_file = self.file_for_node_id(target_id)
        if not step_file:
            # 目标 id 不在当前 step_order（例如被 skip 的审核节点 id）
            if passed and linear_fallback:
                return self._linear_next(node_id, passed=True, linear_fallback=True)
            return RouteDecision(
                next_node_id=target_id,
                next_step_file=None,
                action="fail_closed" if not passed else "finish",
                reason=f"unknown target {target_id}",
            )

        # 判断是前进还是回跳
        try:
            cur_file = self.id_to_file.get(node_id)
            cur_idx = self.step_files.index(cur_file) if cur_file in self.step_files else -1
            next_idx = self.step_files.index(step_file)
            action = "continue" if next_idx >= cur_idx else "jump"
        except ValueError:
            action = "continue"

        return RouteDecision(
            next_node_id=target_id,
            next_step_file=step_file,
            action=action,
            reason=key,
        )

    def resolve_skip_target(
        self,
        skipped_file: str,
        *,
        mode: str,
        risk_code: Optional[str] = None,
    ) -> RouteDecision:
        """人工审核等节点被跳过时，解析应进入的下一节点。"""
        node_id = self.node_id_for_file(skipped_file)
        if not node_id:
            return self._linear_next_file(skipped_file)

        cfg = self.route_config(node_id)
        # 跳过节点时：优先 mode_override 字符串目标；null 则走 on_pass（经 resolve_next）
        override = (cfg.get("mode_override") or {})
        if mode in override and isinstance(override[mode], str) and override[mode]:
            target_id = self._resolve_override(
                node_id, mode, risk_code, override[mode], allow_risk=True
            )
            step_file = self.file_for_node_id(target_id) if target_id else None
            if step_file:
                return RouteDecision(
                    next_node_id=target_id,
                    next_step_file=step_file,
                    action="continue",
                    reason=f"mode_override.{mode}",
                )

        return self.resolve_next(
            node_id, passed=True, mode=mode, risk_code=risk_code, linear_fallback=True
        )

    def _linear_next(
        self, node_id: str, *, passed: bool, linear_fallback: bool
    ) -> RouteDecision:
        cur_file = self.id_to_file.get(node_id)
        if not cur_file:
            return RouteDecision(None, None, "fail_closed" if not passed else "finish", "no file")
        return self._linear_next_file(cur_file, passed=passed)

    def _linear_next_file(self, step_file: str, *, passed: bool = True) -> RouteDecision:
        try:
            idx = self.step_files.index(step_file)
        except ValueError:
            return RouteDecision(None, None, "fail_closed" if not passed else "finish", "not in order")
        # 失败时线性回退不应继续推进（fail-closed），避免静默跳过失败步骤
        if not passed:
            return RouteDecision(None, None, "fail_closed", "linear fail-closed")
        if idx + 1 >= len(self.step_files):
            return RouteDecision(None, None, "finish", "end of step_order")
        nxt = self.step_files[idx + 1]
        return RouteDecision(
            next_node_id=self.file_to_id.get(nxt),
            next_step_file=nxt,
            action="continue",
            reason="linear",
        )

    def invalidate_from(
        self, completed_steps: List[str], from_file: str
    ) -> Tuple[List[str], set]:
        """回跳时清除 from_file 及其后的完成记录。"""
        if from_file not in self.step_files:
            return completed_steps, set()
        start = self.step_files.index(from_file)
        remove = set(self.step_files[start:])
        kept = [s for s in completed_steps if s not in remove]
        return kept, remove
