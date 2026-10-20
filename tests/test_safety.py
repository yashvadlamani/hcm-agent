"""The safety tools and how an emergency on a call uses them. Offline: no model, no network."""

import json

import pytest

from hcm_agent.agent.conversation import EMERGENCY_REPLIES, HCMVoiceAgent
from hcm_agent.tools import ToolCallContext, build_default_gateway, safety
from test_config import VALID
from test_conversation import ScriptedLLM, new_agent, turn_json

CONTEXT = ToolCallContext("clara", "test", "care_management", "m1",
                          frozenset({"care_outreach", "member_verify", "safety_escalation"}))


@pytest.fixture(autouse=True)
def escalations():
    """A fresh in-memory escalation log for every test."""
    log = safety.EscalationStore()
    safety.use_store(log)
    yield log
    safety.use_store(None)


def invoke(tool, **arguments):
    return build_default_gateway().invoke(tool, CONTEXT, {"member_id": "m1", **arguments})


# ---- The tools ----

@pytest.mark.parametrize("statement, kind", [
    ("I'm having chest pain right now", "medical"),
    ("I can't breathe", "medical"),
    ("Sometimes I want to die", "mental_health"),
])
def test_assess_emergency_uses_the_keyword_net(statement, kind):
    data = invoke("assess_emergency", statement=statement).data
    assert data["emergency"] is True and data["kind"] == kind and data["source"] == "keyword"


def test_assess_emergency_accepts_the_models_assessment_only_for_known_kinds():
    reported = invoke("assess_emergency", statement="I feel shaky and confused", reported_kind="medical",
                      reported_reason="possible severe low blood sugar").data
    assert reported == {"emergency": True, "kind": "medical", "reason": "possible severe low blood sugar",
                        "source": "ai"}
    assert invoke("assess_emergency", statement="I'm stressed about refills").data["emergency"] is False
    assert invoke("assess_emergency", statement="I'm stressed", reported_kind="whatever").data["emergency"] is False


def test_scripts_are_fixed_and_only_mention_the_flag_when_the_call_was_flagged():
    medical = invoke("get_911_or_988_script", kind="medical", flagged=True).data["script"]
    assert medical == EMERGENCY_REPLIES["medical"] and "9 1 1" in medical
    crisis = invoke("get_911_or_988_script", kind="mental_health", flagged=False).data["script"]
    assert "9 8 8" in crisis and "flagging" not in crisis and crisis.endswith("Goodbye.")


def test_urgent_alert_is_recorded_with_minimal_details(escalations):
    data = invoke("create_urgent_alert", kind="mental_health", reason="want to die", source="keyword",
                  tenant_id="test", call_id="call-1", name="Maria Lopez", date_of_birth="1990-01-02").data
    assert data["created"] is True and data["queue"] == "behavioral-health-crisis"
    [record] = escalations.records
    assert record["id"] == data["record_id"] and record["type"] == "urgent_alert"
    assert record["priority"] == "urgent" and record["member_id"] == "m1" and record["call_id"] == "call-1"
    assert "Maria" not in json.dumps(record) and "1990" not in json.dumps(record)


def test_urgent_alert_needs_an_assessed_emergency(escalations):
    data = invoke("create_urgent_alert", reason="the member sounded upset").data
    assert data["created"] is False and data["status"] == "rejected"
    assert escalations.records == []


def test_review_task_follow_up_and_routing(escalations):
    review = invoke("create_clinical_review_task", kind="medical", reason="chest pain").data
    routine = invoke("create_clinical_review_task", statement="Asked about splitting insulin doses").data
    follow_up = invoke("create_safety_follow_up", kind="medical", reason="chest pain").data
    assert (review["priority"], routine["priority"]) == ("urgent", "routine")
    assert follow_up["due"] == safety.next_business_day().isoformat()
    assert [r["type"] for r in escalations.records] == ["clinical_review", "clinical_review", "safety_follow_up"]
    assert invoke("route_member_distress", kind="medical").data["queue"] == "nurse-triage"
    assert invoke("route_member_distress").data == {"queue": "care-management-general", "status": "route_selected",
                                                    "live_transfer": False}


def test_safety_tools_need_the_safety_scope():
    care_only = ToolCallContext("clara", "test", "care_management", "m1", frozenset({"care_outreach"}))
    result = build_default_gateway().invoke("create_urgent_alert", care_only, {"member_id": "m1", "kind": "medical"})
    assert not result.allowed and "scope" in result.reason


def test_follow_ups_skip_the_weekend():
    from datetime import date
    assert safety.next_business_day(date(2026, 10, 9)) == date(2026, 10, 12)  # Friday -> Monday


def test_records_are_kept_in_a_file_when_one_is_configured(tmp_path):
    log = safety.EscalationStore(str(tmp_path / "logs" / "escalations.jsonl"))
    safety.use_store(log)
    invoke("create_urgent_alert", kind="medical", reason="chest pain")
    [line] = (tmp_path / "logs" / "escalations.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["type"] == "urgent_alert" and json.loads(line)["status"] == "recorded"


def test_urgent_alerts_are_posted_to_the_webhook_without_blocking(monkeypatch):
    posted = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(safety.urllib.request, "urlopen",
                        lambda request, timeout: posted.append(json.loads(request.data)) or Response())
    monkeypatch.setattr(safety.threading, "Thread",
                        lambda target, args, daemon: type("Now", (), {"start": lambda self: target(*args)})())
    safety.use_store(safety.EscalationStore(webhook_url="https://hooks.example.net/clara"))
    data = invoke("create_urgent_alert", kind="medical", reason="chest pain").data
    assert data["status"] == "notification_queued"
    assert posted[0]["record"]["id"] == data["record_id"] and "nurse-triage" in posted[0]["text"]
    invoke("create_safety_follow_up", kind="medical", reason="chest pain")
    assert len(posted) == 1  # only urgent alerts are posted


# ---- An emergency on a call ----

def test_a_keyword_emergency_is_escalated_through_the_safety_tools(escalations):
    agent, llm = new_agent()
    turn = agent.take_turn("I'm having chest pain right now")
    assert turn.reply == EMERGENCY_REPLIES["medical"] and turn.action == "hang_up" and llm.requests == []
    assert turn.escalation["flagged"] is True and turn.escalation["queue"] == "nurse-triage"
    assert [r["type"] for r in escalations.records] == ["urgent_alert", "clinical_review", "safety_follow_up"]
    assert all(r["member_id"] == "m1" and r["reason"] == "chest pain" and r["source"] == "keyword"
               for r in escalations.records)
    tools = [event["tool"] for event in agent.identity_gateway.audit_log]
    assert tools == ["assess_emergency", "route_member_distress", "create_urgent_alert",
                     "create_clinical_review_task", "create_safety_follow_up", "get_911_or_988_script"]
    assert agent.end_call()["escalation_records"] == turn.escalation["records"]


def test_an_emergency_the_model_spots_is_escalated_with_its_reason(escalations):
    agent, _ = new_agent(turn_json("Okay.", emergency=("mental_health", "says they no longer want to be here")))
    turn = agent.take_turn("I just don't want to be here anymore")
    assert turn.reply == EMERGENCY_REPLIES["mental_health"]
    assert turn.escalation["queue"] == "behavioral-health-crisis"
    assert escalations.records[0]["source"] == "ai"
    assert escalations.records[0]["reason"] == "says they no longer want to be here"


def test_a_call_without_a_member_record_is_still_escalated(escalations):
    agent = HCMVoiceAgent(settings=VALID, llm=ScriptedLLM())
    agent.initialize_call({"name": "Maria", "call_id": "call-9"})
    turn = agent.take_turn("I'm having chest pain")
    assert turn.escalation["flagged"] is True
    assert escalations.records[0]["member_id"] == "unresolved" and escalations.records[0]["call_id"] == "call-9"


def test_if_the_escalation_cannot_be_recorded_clara_still_gives_the_message_without_the_flag(escalations,
                                                                                            monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(escalations, "record", broken)
    agent, _ = new_agent()
    turn = agent.take_turn("I'm having chest pain right now")
    assert turn.action == "hang_up" and "9 1 1" in turn.reply
    assert "flagging" not in turn.reply and turn.escalation["flagged"] is False
