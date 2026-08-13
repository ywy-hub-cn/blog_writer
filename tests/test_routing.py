"""WorkflowRouter 单元测试"""
from pathlib import Path

import pytest

from blog_writer.workflow.routing import WorkflowRouter


SAMPLE_REGISTRY = {
    "step_order": [
        "S000-startup.json",
        "S001-bid-infer.json",
        "S001H-human-review-bid.json",
        "S002-content-prd.json",
        "S004-draft.json",
        "S008-review-draft.json",
        "S009-gate.json",
        "S009H-human-review-gate.json",
        "S010-publish.json",
    ],
    "routing": {
        "step.blog.writer.bid": {
            "on_pass": "step.blog.writer.human_review_bid",
            "on_fail": "step.blog.writer.bid",
            "max_retries": 3,
            "mode_override": {"auto": "step.blog.writer.prd"},
        },
        "step.blog.writer.human_review_bid": {
            "on_pass": "step.blog.writer.prd",
            "on_fail": "step.blog.writer.bid",
            "max_retries": 0,
            "mode_override": {"auto": None},
        },
        "step.blog.writer.review_draft": {
            "on_pass": "step.blog.writer.gate",
            "on_fail": "step.blog.writer.draft",
            "max_retries": 3,
        },
        "step.blog.writer.gate": {
            "on_pass": "step.blog.writer.human_review_gate",
            "on_fail": "step.blog.writer.draft",
            "max_retries": 2,
            "mode_override": {
                "auto": "step.blog.writer.publish",
                "risk_based": {"RK01": "step.blog.writer.publish"},
            },
        },
        "step.blog.writer.human_review_gate": {
            "on_pass": "step.blog.writer.publish",
            "on_fail": "step.blog.writer.draft",
            "max_retries": 0,
        },
        "step.blog.writer.publish": {
            "on_pass": "",
            "on_fail": "step.blog.writer.publish",
            "max_retries": 1,
        },
    },
}

NODE_MAP = {
    "S000-startup.json": {"id": "step.blog.writer.startup", "name": "startup"},
    "S001-bid-infer.json": {"id": "step.blog.writer.bid", "name": "bid"},
    "S001H-human-review-bid.json": {
        "id": "step.blog.writer.human_review_bid",
        "name": "review",
    },
    "S002-content-prd.json": {"id": "step.blog.writer.prd", "name": "prd"},
    "S004-draft.json": {"id": "step.blog.writer.draft", "name": "draft"},
    "S008-review-draft.json": {"id": "step.blog.writer.review_draft", "name": "review"},
    "S009-gate.json": {"id": "step.blog.writer.gate", "name": "gate"},
    "S009H-human-review-gate.json": {
        "id": "step.blog.writer.human_review_gate",
        "name": "gate_review",
    },
    "S010-publish.json": {"id": "step.blog.writer.publish", "name": "publish"},
}


def _load(name: str):
    if name not in NODE_MAP:
        raise FileNotFoundError(name)
    return NODE_MAP[name]


@pytest.fixture
def router():
    return WorkflowRouter(SAMPLE_REGISTRY, SAMPLE_REGISTRY["step_order"], _load)


class TestWorkflowRouter:
    def test_auto_mode_skips_bid_review(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.bid", passed=True, mode="auto"
        )
        assert d.next_node_id == "step.blog.writer.prd"
        assert d.next_step_file == "S002-content-prd.json"

    def test_supervised_goes_to_review(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.bid", passed=True, mode="supervised"
        )
        assert d.next_node_id == "step.blog.writer.human_review_bid"

    def test_review_fail_jumps_to_draft(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.review_draft", passed=False, mode="auto"
        )
        assert d.action == "jump"
        assert d.next_step_file == "S004-draft.json"

    def test_gate_manual_keeps_review(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.gate", passed=True, mode="manual", risk_code="RK01"
        )
        assert d.next_step_file == "S009H-human-review-gate.json"

    def test_gate_auto_risk_still_to_publish(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.gate", passed=True, mode="auto", risk_code="RK01"
        )
        assert d.next_step_file == "S010-publish.json"


    def test_publish_finish(self, router: WorkflowRouter):
        d = router.resolve_next(
            "step.blog.writer.publish", passed=True, mode="auto"
        )
        assert d.action == "finish"

    def test_invalidate_from(self, router: WorkflowRouter):
        completed = [
            "S000-startup.json",
            "S001-bid-infer.json",
            "S004-draft.json",
            "S008-review-draft.json",
        ]
        kept, removed = router.invalidate_from(completed, "S004-draft.json")
        assert "S004-draft.json" not in kept
        assert "S008-review-draft.json" in removed
        assert "S000-startup.json" in kept

    def test_skip_target_for_auto_review(self, router: WorkflowRouter):
        d = router.resolve_skip_target(
            "S001H-human-review-bid.json", mode="auto"
        )
        # mode_override.auto is null → fall through to on_pass = prd
        assert d.next_step_file == "S002-content-prd.json"
        assert d.action in ("continue", "finish")

    def test_resolve_override_risk_does_not_apply_in_manual(self, router: WorkflowRouter):
        # 与 gate 行为一致：manual 忽略 risk_based
        target = router._resolve_override(
            "step.blog.writer.gate",
            "manual",
            "RK01",
            "step.blog.writer.human_review_gate",
            allow_risk=True,
        )
        assert target == "step.blog.writer.human_review_gate"

    def test_resolve_override_mode_then_risk(self, router: WorkflowRouter):
        # risk_based 可覆盖 mode_override 字符串
        target = router._resolve_override(
            "step.blog.writer.gate",
            "auto",
            "RK01",
            "step.blog.writer.human_review_gate",
            allow_risk=True,
        )
        assert target == "step.blog.writer.publish"
