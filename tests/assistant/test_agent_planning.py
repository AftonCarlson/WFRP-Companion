from __future__ import annotations

import pytest

from wfrp_companion.assistant import agent_planning


def valid_plan_payload() -> dict[str, object]:
    return {
        "intent": "statline_lookup",
        "plan_summary": "Find regular Ogre statline evidence and exclude Rat Ogre.",
        "subject": {
            "canonical": "ogres",
            "surface": "ogres",
            "include_terms": ["ogre", "ogres"],
            "exclude_terms": ["rat ogre", "rat ogres", "rat"],
            "book_title_hints": [],
            "page_hints": [],
            "notes": None,
        },
        "requirements": [
            {
                "id": "regular_ogre_stats",
                "requirement_type": "statline_evidence",
                "subject": {
                    "canonical": "ogres",
                    "surface": "ogres",
                    "include_terms": ["ogre", "ogres"],
                    "exclude_terms": ["rat ogre", "rat ogres", "rat"],
                    "book_title_hints": [],
                    "page_hints": [],
                    "notes": None,
                },
                "required_terms": ["ogre"],
                "excluded_terms": ["rat ogre", "rat"],
                "object_type_hints": ["stat_block", "monster_profile"],
                "structured_lookup_policy": "not_primary",
                "structured_object_shape_hints": [],
                "structured_content_kind_hints": [],
                "structured_entity_kind_hints": [],
                "table_number_hints": [],
                "min_accepted_hits": 1,
                "required": True,
            }
        ],
        "planned_actions": [
            {
                "tool_name": "search_library",
                "requirement_id": "regular_ogre_stats",
                "purpose": "Search checked books for regular Ogre statistics.",
                "arguments": {
                    "query": "ogre statistics statline",
                    "intent": "statline_lookup",
                    "subject": "ogres",
                    "limit": 8,
                    "include_terms": ["ogre", "ogres"],
                    "exclude_terms": ["rat ogre", "rat"],
                    "object_type_hints": ["stat_block", "monster_profile"],
                    "book_title_hints": [],
                    "page_hints": [],
                },
            }
        ],
    }


def test_parse_valid_research_plan_normalizes_and_round_trips() -> None:
    parsed = agent_planning.parse_research_plan(
        valid_plan_payload(),
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
        provider_call_id="call-plan",
    )

    assert parsed.id == "plan-1"
    assert parsed.research_run_id == "research-1"
    assert parsed.revision == 1
    assert parsed.provider_call_id == "call-plan"
    assert parsed.intent == "statline_lookup"
    assert parsed.subject.include_terms == ("ogre", "ogres")
    assert parsed.subject.exclude_terms == ("rat ogre", "rat ogres", "rat")
    assert parsed.requirements[0].id == "regular_ogre_stats"
    assert parsed.requirements[0].subject.canonical == "ogres"
    assert parsed.requirements[0].excluded_terms == ("rat ogre", "rat")
    assert parsed.planned_actions[0].requirement_id == "regular_ogre_stats"
    assert parsed.to_json() == valid_plan_payload()


def test_parse_research_plan_accepts_short_provider_requirement_ids() -> None:
    payload = valid_plan_payload()
    payload["requirements"][0]["id"] = "r1"
    payload["planned_actions"][0]["requirement_id"] = "r1"

    parsed = agent_planning.parse_research_plan(
        payload,
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
        provider_call_id="call-plan",
    )

    assert parsed.requirements[0].id == "r1"
    assert parsed.planned_actions[0].requirement_id == "r1"


@pytest.mark.parametrize(
    ("mutator", "message"),
    (
        (
            lambda payload: payload["requirements"].append(
                payload["requirements"][0].copy()
            ),
            "duplicate requirement id",
        ),
        (
            lambda payload: payload.__setitem__(
                "plan_summary",
                "x" * 501,
            ),
            "plan_summary",
        ),
        (
            lambda payload: payload["planned_actions"][0].__setitem__(
                "tool_name",
                "raw_sql",
            ),
            "unknown tool",
        ),
        (
            lambda payload: payload["planned_actions"][0].__setitem__(
                "requirement_id",
                "missing_requirement",
            ),
            "unknown requirement",
        ),
        (
            lambda payload: payload["planned_actions"][0]["arguments"].__setitem__(
                "query",
                "x" * 241,
            ),
            "argument",
        ),
        (
            lambda payload: payload["requirements"][0].__setitem__(
                "structured_lookup_policy",
                "always",
            ),
            "unknown structured_lookup_policy",
        ),
    ),
)
def test_parse_research_plan_rejects_invalid_payloads(mutator, message: str) -> None:
    payload = valid_plan_payload()
    mutator(payload)

    with pytest.raises(agent_planning.PlanValidationError, match=message):
        agent_planning.parse_research_plan(
            payload,
            research_run_id="research-1",
            plan_id="plan-1",
            revision=1,
        )


@pytest.mark.parametrize(
    ("payload_factory", "kwargs", "message"),
    (
        (valid_plan_payload, {"revision": 0}, "revision"),
        (
            lambda: {**valid_plan_payload(), "intent": "unknown"},
            {},
            "unknown intent",
        ),
        (
            lambda: {**valid_plan_payload(), "requirements": []},
            {},
            "requirements must not be empty",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "id": f"req_{index}",
                    }
                    for index in range(7)
                ],
            },
            {},
            "requirements may include at most 6",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "planned_actions": valid_plan_payload()["planned_actions"] * 5,
            },
            {},
            "planned_actions may include at most 4",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "id": "bad-id",
                    }
                ],
            },
            {},
            "invalid requirement id",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "requirement_type": "unknown",
                    }
                ],
            },
            {},
            "unknown requirement_type",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "min_accepted_hits": 0,
                    }
                ],
            },
            {},
            "min_accepted_hits",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "required": "yes",
                    }
                ],
            },
            {},
            "required must be a boolean",
        ),
        (
            lambda: {**valid_plan_payload(), "subject": "ogre"},
            {},
            "subject must be an object",
        ),
        (
            lambda: {**valid_plan_payload(), "requirements": "bad"},
            {},
            "requirements must be a list",
        ),
        (
            lambda: {**valid_plan_payload(), "requirements": ["bad"]},
            {},
            "requirements entries must be objects",
        ),
        (
            lambda: {**valid_plan_payload(), "intent": ""},
            {},
            "intent must be a non-empty string",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {**valid_plan_payload()["subject"], "notes": 42},
            },
            {},
            "notes must be a string or null",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {**valid_plan_payload()["subject"], "notes": "x" * 241},
            },
            {},
            "notes must be at most",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {
                    **valid_plan_payload()["subject"],
                    "include_terms": "ogre",
                },
            },
            {},
            "include_terms must be a list",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {
                    **valid_plan_payload()["subject"],
                    "include_terms": [f"term-{index}" for index in range(13)],
                },
            },
            {},
            "include_terms may include at most",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {
                    **valid_plan_payload()["subject"],
                    "include_terms": [7],
                },
            },
            {},
            "include_terms values must be strings",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "subject": {
                    **valid_plan_payload()["subject"],
                    "include_terms": ["x" * 241],
                },
            },
            {},
            "include_terms values must be bounded",
        ),
        (
            lambda: {
                **valid_plan_payload(),
                "requirements": [
                    {
                        **valid_plan_payload()["requirements"][0],
                        "min_accepted_hits": True,
                    }
                ],
            },
            {},
            "min_accepted_hits must be an integer",
        ),
    ),
)
def test_parse_research_plan_rejects_edge_invalid_payloads(
    payload_factory,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(agent_planning.PlanValidationError, match=message):
        agent_planning.parse_research_plan(
            payload_factory(),
            research_run_id="research-1",
            plan_id="plan-1",
            revision=kwargs.pop("revision", 1),
        )


def test_parse_research_plan_deduplicates_and_skips_blank_terms() -> None:
    payload = valid_plan_payload()
    payload["subject"]["include_terms"] = ["Ogre", " ", "ogre", "Ogres"]
    payload["subject"]["page_hints"] = None
    payload["subject"]["notes"] = "   "

    parsed = agent_planning.parse_research_plan(
        payload,
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
    )

    assert parsed.subject.include_terms == ("Ogre", "Ogres")
    assert parsed.subject.page_hints == ()
    assert parsed.subject.notes is None


def test_planning_tool_schema_is_strict_for_nested_objects() -> None:
    schema = agent_planning.planning_tool_definition().parameters

    assert_object_is_strict(schema)
    assert_object_is_strict(schema["properties"]["subject"])
    requirement_item = schema["properties"]["requirements"]["items"]
    assert_object_is_strict(requirement_item)
    assert_object_is_strict(requirement_item["properties"]["subject"])
    action_item = schema["properties"]["planned_actions"]["items"]
    assert_object_is_strict(action_item)
    arguments_schema = action_item["properties"]["arguments"]
    assert_object_is_strict(arguments_schema)


def test_planning_tool_schema_publishes_requirement_id_pattern() -> None:
    schema = agent_planning.planning_tool_definition().parameters
    requirement_item = schema["properties"]["requirements"]["items"]
    action_item = schema["properties"]["planned_actions"]["items"]

    assert requirement_item["properties"]["id"]["pattern"] == (
        agent_planning.REQUIREMENT_ID_PATTERN
    )
    assert action_item["properties"]["requirement_id"]["pattern"] == (
        agent_planning.REQUIREMENT_ID_PATTERN
    )


def test_planning_tool_schema_publishes_parser_bounds() -> None:
    schema = agent_planning.planning_tool_definition().parameters
    properties = schema["properties"]
    requirement_array = properties["requirements"]
    requirement_item = requirement_array["items"]
    planned_action_array = properties["planned_actions"]
    action_item = planned_action_array["items"]

    assert properties["plan_summary"]["maxLength"] == (
        agent_planning.MAX_PLAN_SUMMARY_CHARS
    )
    assert requirement_array["maxItems"] == 6
    assert planned_action_array["maxItems"] == 4
    assert requirement_item["properties"]["min_accepted_hits"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 6,
    }
    assert requirement_item["properties"]["object_type_hints"]["maxItems"] == 8
    assert (
        requirement_item["properties"]["subject"]["properties"]["include_terms"][
            "maxItems"
        ]
        == agent_planning.MAX_TERMS
    )
    assert (
        requirement_item["properties"]["required_terms"]["maxItems"]
        == agent_planning.MAX_TERMS
    )
    assert (
        action_item["properties"]["arguments"]["properties"]["include_terms"][
            "maxItems"
        ]
        == agent_planning.MAX_TERMS
    )


def assert_object_is_strict(schema: object) -> None:
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
