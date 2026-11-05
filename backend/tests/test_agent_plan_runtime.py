import tempfile
from pathlib import Path

import pytest

from app.agent_plan_runtime import AgentPlanExecutionController
from app.agent_plan_sqlite_store import SQLiteAgentPlanStore
from app.agent_service import RobotAgentService


@pytest.fixture
def controller() -> AgentPlanExecutionController:
    directory = tempfile.TemporaryDirectory()
    store = SQLiteAgentPlanStore(Path(directory.name) / "plans.sqlite3")
    instance = AgentPlanExecutionController(store)
    instance._test_directory = directory
    return instance


def test_safe_chat_request_runs_and_completes(controller) -> None:
    result = controller.run(
        "检查当前状态",
        {"name": "get_robot_status", "tool_family": "device"},
        lambda: {"ok": True, "message": "状态正常"},
    )

    trace = result["execution_plan"]
    assert trace["status"] == "completed"
    assert trace["step_status"] == "verified"
    assert trace["evaluation"]["passed"] is True
    assert [event.event_type for event in controller.store.events(trace["id"])] == [
        "plan_created",
        "step_started",
        "step_verified",
    ]


def test_high_risk_request_stays_at_confirmation(controller) -> None:
    session = controller.begin(
        "向前移动一米",
        {"name": "drive_robot", "tool_family": "motion"},
    )
    result = controller.complete(
        session,
        {
            "ok": True,
            "message": "请确认执行",
            "pending_action": {"id": "pending-1"},
        },
    )

    assert result["execution_plan"]["status"] == "awaiting_confirmation"
    assert result["execution_plan"]["step_status"] == "awaiting_confirmation"
    assert controller.store.events(session.plan_id)[-1].event_type == (
        "step_awaiting_confirmation"
    )

    confirmed = controller.complete_pending_action(
        "pending-1",
        approved=True,
        result={"ok": True, "message": "执行完成"},
    )
    assert confirmed["execution_plan"]["status"] == "completed"
    assert controller.store.plan_id_for_action("pending-1") is None


def test_cad_preflight_confirmation_is_not_marked_completed(controller):
    session=controller.begin('复制选中图形',{'name':'drawing_design','operation':'modify','tool_family':'cad'})
    paused=controller.complete(session,{'ok':True,'pending_action':{'id':'cad-confirm'},'message':'请确认应用'})
    assert paused['execution_plan']['status']=='awaiting_confirmation'
    assert paused['execution_plan']['step_status']=='awaiting_confirmation'
    assert controller.store.plan_id_for_action('cad-confirm')==session.plan_id
    result=controller.complete_pending_action('cad-confirm',approved=True,
        result={'ok':True,'message':'已保存新版本','machine_assertions':{'verified':True}})
    assert result['execution_plan']['status']=='completed'
    assert controller.store.plan_id_for_action('cad-confirm') is None


def test_clarification_with_ok_true_cannot_pass_execution_verification(controller):
    session=controller.begin('旋转图形',{'name':'drawing_design','operation':'modify','tool_family':'cad'})
    result=controller.complete(session,{'ok':True,'clarification_question':'请补方向','message':'请补方向'})
    assert result['execution_plan']['status']!='completed'
    assert result['execution_plan']['step_status']!='verified'


def test_rejected_pending_action_cancels_original_plan(controller) -> None:
    session = controller.begin(
        "启动任务",
        {"name": "execute_prepared_mission", "tool_family": "motion"},
    )
    controller.complete(
        session,
        {
            "ok": True,
            "message": "请确认执行",
            "pending_action": {"id": "pending-cancel"},
        },
    )

    cancelled = controller.complete_pending_action(
        "pending-cancel",
        approved=False,
        result={"ok": True, "message": "已取消"},
    )
    assert cancelled["execution_plan"]["status"] == "cancelled"
    assert cancelled["execution_plan"]["step_status"] == "skipped"
    assert controller.store.events(session.plan_id)[-1].event_type == "plan_cancelled"


def test_cad_repair_is_recorded_once_before_completion(controller) -> None:
    result = controller.run(
        "移动选中的中心圆",
        {
            "name": "drawing_design",
            "operation": "modify",
            "tool_family": "cad",
            "selected_project_id": "project-1",
            "selected_variant_id": "variant-1",
        },
        lambda: {
            "ok": True,
            "message": "已生成修复后的候选方案",
            "machine_assertions": {"verified": True, "failure_codes": []},
            "edit_repair": {
                "attempted": True,
                "recovered": True,
                "strategy": "restore_non_targets",
            },
        },
    )

    trace = result["execution_plan"]
    assert trace["status"] == "completed"
    assert trace["repair_count"] == 1
    assert trace["evaluation"]["passed"] is True
    assert [event.event_type for event in controller.store.events(trace["id"])] == [
        "plan_created",
        "step_started",
        "plan_repair_started",
        "step_started",
        "step_verified",
    ]


def test_executor_exception_is_persisted_as_failed(controller) -> None:
    def fail():
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        controller.run(
            "检查当前状态",
            {"name": "get_robot_status"},
            fail,
        )

    database = controller.store._connect()
    try:
        plan_id = database.execute("SELECT plan_id FROM agent_plans").fetchone()[0]
    finally:
        database.close()
    plan = controller.store.get(plan_id)
    assert plan is not None
    assert plan.status == "failed"
    assert plan.steps[0].status == "failed"


def test_robot_agent_chat_uses_strict_plan_runtime(controller, monkeypatch) -> None:
    service = RobotAgentService()
    monkeypatch.setattr("app.agent_service.agent_plan_runtime", controller)
    monkeypatch.setattr(
        service,
        "_chat_impl",
        lambda *args, **kwargs: {"ok": True, "message": "完成"},
    )

    result = service.chat(
        "检查状态",
        [],
        mode="advanced",
        route={"name": "get_robot_status", "tool_family": "device"},
    )

    assert result["execution_plan"]["status"] == "completed"
    assert controller.store.get(result["execution_plan"]["id"]) is not None


def test_robot_agent_stream_uses_same_strict_plan_runtime(controller, monkeypatch) -> None:
    service = RobotAgentService()
    monkeypatch.setattr("app.agent_service.agent_plan_runtime", controller)
    monkeypatch.setattr(
        service,
        "_chat_stream_impl",
        lambda *args, **kwargs: iter(
            [
                {"type": "delta", "text": "处理中"},
                {"type": "result", "ok": True, "message": "完成"},
            ]
        ),
    )

    events = list(
        service.chat_stream(
            "检查状态",
            [],
            mode="advanced",
            route={"name": "get_robot_status", "tool_family": "device"},
        )
    )

    assert events[-1]["execution_plan"]["status"] == "completed"
    assert events[-1]["execution_plan"]["evaluation"]["passed"] is True
