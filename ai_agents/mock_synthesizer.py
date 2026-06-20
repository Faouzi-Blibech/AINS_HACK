"""Mock synthesizer.

In divergence mode, new tool calls can appear after the fork point that have no
recorded response. This component generates a plausible response from the tool's
schema and surrounding context, so replay can continue without hitting a live
endpoint.

The synthesizer has two paths:
- LLM path: asks the model for a contextually plausible response that conforms
  to the tool's JSON schema. Returns a high-confidence AIResult.
- Offline fallback: on LLMNotConfigured, json.JSONDecodeError, KeyError, or
  ValueError, builds a minimal skeleton from the schema's declared property
  types (string -> "", number/integer -> 0, boolean -> False, object -> {},
  array -> []). Returns a low-confidence AIResult. Never raises.
"""
from __future__ import annotations

import json
from typing import Any

import ai_agents.confidence as confidence
from ai_agents import llm
from ai_agents.prompts import MOCK_SYNTH_SYSTEM, mock_synth_user

# Confidence level for a clean LLM-generated response.
_HIGH_CONFIDENCE = 0.85

# Confidence level for the deterministic schema-shaped fallback.
_LOW_CONFIDENCE = 0.2

# Type-default map: maps a JSON schema type string to its zero-value.
_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "",
    "number": 0,
    "integer": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _skeleton_from_schema(schema: dict | None) -> Any:
    """Build a minimal placeholder object from a JSON schema's declared types.

    Handles a missing or empty schema by returning {}. Recurses one level into
    nested object properties. Unknown types default to None.
    """
    if not schema:
        return {}

    schema_type = schema.get("type")
    properties = schema.get("properties")

    # If the schema is not typed or not typed as object, fall back.
    if schema_type != "object" and not properties:
        if schema_type in _TYPE_DEFAULTS:
            return _TYPE_DEFAULTS[schema_type]
        return {}

    # Build an object skeleton from declared properties.
    if not properties:
        return {}

    result: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type")
        if prop_type == "object":
            # Recurse one level to fill nested object properties.
            nested_props = prop_schema.get("properties")
            if nested_props:
                nested: dict[str, Any] = {}
                for nested_name, nested_schema in nested_props.items():
                    nested_type = nested_schema.get("type")
                    nested[nested_name] = _TYPE_DEFAULTS.get(nested_type)
                result[prop_name] = nested
            else:
                result[prop_name] = {}
        elif prop_type in _TYPE_DEFAULTS:
            result[prop_name] = _TYPE_DEFAULTS[prop_type]
        else:
            result[prop_name] = None

    return result


def _fallback(schema: dict | None, reason: str) -> confidence.AIResult[dict]:
    """Return a low-confidence skeleton result with a rationale."""
    skeleton = _skeleton_from_schema(schema)
    if not isinstance(skeleton, dict):
        skeleton = {}
    rationale = (
        f"Schema-shaped placeholder (no LLM response available: {reason}). "
        "Values are type defaults, not contextually meaningful."
    )
    return confidence.wrap(skeleton, _LOW_CONFIDENCE, rationale)


def synthesize(
    tool: str,
    arguments: dict,
    schema: dict | None,
    context: dict,
) -> confidence.AIResult[dict]:
    """Generate a plausible response for an unrecorded tool call.

    Parameters
    ----------
    tool:
        The tool name (e.g. "get_ticket_info").
    arguments:
        The arguments the tool was called with.
    schema:
        The JSON schema for the expected response object. May be None or empty.
    context:
        Surrounding context for the replay (run_id, step_id, etc.).

    Returns
    -------
    AIResult[dict]
        High-confidence when the LLM produced a valid JSON object; low-confidence
        when the offline fallback was used. Never raises.
    """
    try:
        raw = llm.llm_complete(
            system=MOCK_SYNTH_SYSTEM,
            user=mock_synth_user(
                tool=tool,
                arguments=arguments,
                schema=schema,
                context=context,
            ),
            model=llm.cheap_model(),
            json_schema=schema,
        )
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM response is not a JSON object: {type(parsed).__name__}")
        rationale = (
            f"LLM synthesized a plausible response for tool '{tool}' "
            "from its schema and context."
        )
        return confidence.wrap(parsed, _HIGH_CONFIDENCE, rationale)

    except llm.LLMNotConfigured:
        return _fallback(schema, "LLM not configured")
    except json.JSONDecodeError as exc:
        return _fallback(schema, f"JSON parse error: {exc}")
    except (KeyError, ValueError) as exc:
        return _fallback(schema, str(exc))
