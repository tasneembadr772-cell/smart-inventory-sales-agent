"""
Utility functions for the AI Agent orchestration layer.

Provides safe parameter extraction from Gemini protobuf types, JSON serialization
helpers, and formatting utilities for agent audit trails.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def proto_to_python(val: Any) -> Any:
    """
    Recursively converts Gemini/Protobuf MapComposite, Struct, RepeatedComposite,
    or primitive types into clean Python native dicts, lists, and values.
    """
    if val is None:
        return None
    # Check if it has items() (MapComposite or dict-like)
    if hasattr(val, "items"):
        return {str(k): proto_to_python(v) for k, v in val.items()}
    # Check if it's a sequence / repeated composite (excluding strings and bytes)
    if isinstance(val, (list, tuple)) or hasattr(val, "__iter__") and not isinstance(val, (str, bytes, bytearray)):
        return [proto_to_python(item) for item in val]
    # Check if integer-like float (e.g. 5.0 -> 5)
    if isinstance(val, float) and val.is_integer():
        return int(val)
    return val


def make_json_serializable(val: Any) -> Any:
    """
    Recursively transforms objects (including Decimals and datetime) into JSON-serializable types.
    """
    if isinstance(val, Decimal):
        return str(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: make_json_serializable(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [make_json_serializable(v) for v in val]
    return val
