"""Fail-closed validator for the keywords used by the frozen bundled schemas.

This deliberately does not pretend to implement all of JSON Schema. Unknown
validation keywords raise an error instead of silently accepting a document.
"""
from __future__ import annotations
from .common import W2Error

ANNOTATIONS = {"$schema", "$id", "title", "description", "x-semantic-checks", "x-host-checks"}
KEYWORDS = {"type", "required", "properties", "additionalProperties", "items", "minItems",
            "maxItems", "uniqueItems", "minLength", "enum", "const", "oneOf", "$ref"}


def validate(value, schema, schemas=None, path="$"):
    schemas = schemas or {}
    unknown = set(schema) - KEYWORDS - ANNOTATIONS
    if unknown:
        raise W2Error("E_SCHEMA", "unsupported schema keywords: " + str(sorted(unknown)), path)
    if "$ref" in schema:
        if schema["$ref"] not in schemas:
            raise W2Error("E_SCHEMA", "unregistered schema reference", path)
        return validate(value, schemas[schema["$ref"]], schemas, path)
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                validate(value, branch, schemas, path)
                matches += 1
            except W2Error:
                pass
        if matches != 1:
            raise W2Error("E_SCHEMA", "expected exactly one schema branch", path)
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    predicates = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                  "string": lambda v: isinstance(v, str), "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                  "null": lambda v: v is None, "boolean": lambda v: isinstance(v, bool)}
    if types and not any(predicates[t](value) for t in types):
        raise W2Error("E_SCHEMA", "wrong JSON type", path)
    if "const" in schema and value != schema["const"]:
        raise W2Error("E_SCHEMA", "constant mismatch", path)
    if "enum" in schema and value not in schema["enum"]:
        raise W2Error("E_SCHEMA", "not in enum", path)
    if isinstance(value, dict):
        if set(schema.get("required", [])) - set(value):
            raise W2Error("E_SCHEMA", "missing required properties", path)
        properties = schema.get("properties", {})
        extra = set(value) - set(properties)
        policy = schema.get("additionalProperties", True)
        if extra and policy is False:
            raise W2Error("E_SCHEMA", "unknown properties: " + str(sorted(extra)), path)
        for key, child in value.items():
            child_schema = properties.get(key, policy if isinstance(policy, dict) else {})
            validate(child, child_schema, schemas, path + "." + key)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise W2Error("E_SCHEMA", "array length outside bounds", path)
        if schema.get("uniqueItems") and any(v in value[:i] for i, v in enumerate(value)):
            raise W2Error("E_SCHEMA", "duplicate array value", path)
        for i, child in enumerate(value):
            validate(child, schema.get("items", {}), schemas, f"{path}[{i}]")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise W2Error("E_SCHEMA", "string too short", path)
