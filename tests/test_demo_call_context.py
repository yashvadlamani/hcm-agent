"""Fictional care-scenario metadata used only by the local interactive CLI."""

from hcm_agent.workflows.member_data import (
    demo_call_context_for_name,
    identity_record_for_name,
    load_demo_members,
)


def test_himanshu_demo_context_uses_requested_diabetes_example():
    context = demo_call_context_for_name("Himanshu Gupta")

    assert context["data_status"] == "fictional_demo_only"
    assert context["for"] == "diabetes management"
    assert context["risk_drivers"] == [
        "HbA1c above 7.5% at last check",
        "Missed metformin refills in the last 60 days",
        "No endocrinologist visit in over 12 months",
        "ER visit for low blood sugar in last 90 days",
        "Overdue annual diabetic eye exam",
    ]


def test_unique_first_name_resolves_demo_member_and_context():
    assert identity_record_for_name("Himanshu")["name"] == "Himanshu Gupta"
    assert demo_call_context_for_name("Himanshu")["for"] == "diabetes management"


def test_each_demo_member_has_distinct_fictional_scenario():
    members = load_demo_members()
    contexts = [demo_call_context_for_name(member["name"]) for member in members]

    assert len(contexts) == 5
    assert all(context["data_status"] == "fictional_demo_only" for context in contexts)
    assert len({context["for"] for context in contexts}) == len(contexts)
    assert all(1 <= len(context["risk_drivers"]) <= 5 for context in contexts)
    assert all(len(driver) <= 100 for context in contexts for driver in context["risk_drivers"])
    assert all(context.get("care_team_record") for context in contexts)
    assert all(context.get("goals_on_file") for context in contexts)
    assert all(context.get("follow_up_plan") for context in contexts)
    assert all(context["data_status"] == "fictional_demo_only" for context in contexts)
