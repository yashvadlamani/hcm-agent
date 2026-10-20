import json

from hcm_agent.agent.llm import _preserve_exact_policy_answer
from hcm_agent.tools.domains import lookup_policy
from hcm_agent.tools.providers import search_provider_directory


def test_policy_out_of_pocket_answer_is_extracted_from_the_retrieved_pdf_table():
    result = lookup_policy({"query": "What is the out-of-pocket maximum?"})

    assert result["answer"] == (
        "For the 2025 plan summary, the out-of-pocket maximum is: "
        "Individual: Participating $9,200; Non-Participating Unlimited. "
        "Family: Participating $18,400; Non-Participating Unlimited."
    )
    assert result["answer_page"] == 1


def test_policy_deductible_answer_is_extracted_from_the_retrieved_pdf_table():
    result = lookup_policy({"query": "How much is my deductible?"})

    assert result["answer"] == (
        "For the 2025 plan summary, the overall deductible is: "
        "Individual: Participating $1,000; Non-Participating $15,000. "
        "Family: Participating $2,000; Non-Participating $45,000."
    )
    assert result["answer_page"] == 1


def test_final_model_reply_cannot_alter_an_extracted_policy_table_answer():
    canonical = ("For the 2025 plan summary, the out-of-pocket maximum is: "
                 "Individual: Participating $9,200; Non-Participating Unlimited. "
                 "Family: Participating $18,400; Non-Participating Unlimited.")
    raw = json.dumps({"reply": "Your out-of-pocket maximum is $4,500.", "sentiment": 0.5})

    result = json.loads(_preserve_exact_policy_answer(raw, {"answer": canonical, "answer_page": 1}))

    assert result["reply"] == canonical + " Source: page 1."


def test_provider_directory_includes_next_unbooked_demo_slots():
    result = search_provider_directory({"specialty": "endocrinology", "area": "Schaumburg"})

    option = result["options"][0]
    assert result["status"] == "results_found"
    assert len(option["next_available_slots"]) == 3
    assert all(slot["day"] not in {"Saturday", "Sunday"} for slot in option["next_available_slots"])
    assert option["availability_note"].startswith("Fictional demo")
