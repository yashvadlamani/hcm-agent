"""The tool inventory exposed to Clara's eight capability nodes.

This module is intentionally small: ``catalog.py`` owns schemas and the ``@tool``
factory, while this file makes the graph's capability-to-tool contract easy to read.
"""

from .catalog import FAMILIES, build_tools

CAPABILITY_FAMILIES = {
    "capability_1_outreach": ("outreach",),
    "capability_2_communication": ("communication",),
    "capability_3_identity": ("identity",),
    "capability_4_care_context": ("care",),
    "capability_5_knowledge_policy": ("guidance",),
    "capability_6_navigation": ("navigation",),
    "capability_7_safety": ("safety",),
    "capability_8_security": ("security",),
}

CAPABILITY_TOOLS = {
    capability: tuple(tool_name for family in families for tool_name in FAMILIES[family])
    for capability, families in CAPABILITY_FAMILIES.items()
}

# Stages control which capability tools the GPT model can select. The graph keeps
# every capability node visible, but a care conversation cannot call pre-dial or
# identity tools after verification has completed.
CAPABILITY_STAGES = {
    "pre_call": ("capability_1_outreach", "capability_2_communication"),
    "identity": ("capability_3_identity",),
    "care": ("capability_4_care_context", "capability_5_knowledge_policy",
             "capability_6_navigation", "capability_7_safety", "capability_8_security"),
}


def build_capability_tools() -> dict[str, list]:
    """Create the decorated LangChain tools owned by every capability node."""
    return {
        capability: build_tools(families=families)
        for capability, families in CAPABILITY_FAMILIES.items()
    }
