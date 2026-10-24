"""Versioned source/type checks with local semantic-error isolation.

Derived from frozen parent validate_spec.py; that file remains unchanged.
"""
from __future__ import annotations
import itertools
import math
import re
from ..common import W2Error, digest, spans, quantity
from ..kernels import normalize_quantities
from ..registry import RELATIONS, TYPES, COMPATIBLE
from ..schema import validate
from .contract import (ANCHORS, OBJECT_ANCHORS, NUMBER, INPUT_OWNERS, LABEL_GROUPS,
                       BRANCH_RELATIONS, SKILL_ID, LIMITS, contract_hash)


def parse_plan(raw):
    import json
    text = raw.strip()
    if text.startswith("```json\n") and text.endswith("\n```") and text.count("```") == 2:
        text = text[8:-4]
    try:
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate JSON key')
                result[key]=value
            return result
        def decimal(value):
            result=float(value)
            if not math.isfinite(result):raise ValueError('nonfinite JSON number')
            return result
        return json.loads(text,object_pairs_hook=pairs,parse_float=decimal,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, TypeError) as exc:
        raise W2Error("E_SCHEMA", "invalid plan JSON") from exc


class Context:
    """Created only by the host, never from model-provided status fields.

    Numeric binding is deliberately conservative. A binding with ambiguous
    ownership stays blocked; reviewed semantic certificates can only be
    supplied by the offline preflight and are versioned with the question.
    """
    def __init__(self, question, schema, resources, *, binding_certificates=None,
                 expected_outputs=None, source_load_inventory=None, constants=None):
        self.question, self.schema, self.resources = question, schema, resources
        self.contract_identity = contract_hash()
        self.schema_identity = digest(schema)
        self.resource_identities = {key: digest(value) for key, value in resources.items()}
        self.spans = {s["span_id"]: s for s in spans(question)}
        self.certificates = binding_certificates or {}
        self.expected_outputs = expected_outputs
        self.load_inventory = source_load_inventory
        self.constants = constants or {}
        self.question_hash = digest(question.encode("utf-8"))

    def resource(self, key):
        if key not in self.resources:
            raise W2Error("E_SOURCE", "unregistered resource", key)
        item = self.resources[key]
        if digest(item) != self.resource_identities[key]:
            raise W2Error("E_SOURCE", "resource version changed after context freeze", key)
        required = {"source_id", "version", "sha256", "locator", "quantity"}
        if not required <= set(item) or digest(item["quantity"]) != item["sha256"]:
            raise W2Error("E_SOURCE", "resource identity mismatch", key)
        return item["quantity"]

    def bound_input(self, item, objects):
        field = item["input_id"]
        span = self.spans.get(item["source_span_id"])
        if not span or item["quote"] not in span["text"]:
            raise W2Error("E_INPUT_BINDING", "quote not in original source span", field)
        obj = objects.get(item["object_id"])
        if not obj:
            raise W2Error("E_TYPE", "unknown input object", field)
        kind, value, unit, quote = item["quantity_type"], item["value"], item["unit"], item["quote"]
        if kind not in TYPES:
            raise W2Error("E_TYPE", "unknown quantity type", field)
        if kind not in ANCHORS:
            raise W2Error("E_INPUT_BINDING", "quantity requires a registered source, not a free input", field)
        if obj['object_type'] not in INPUT_OWNERS[kind]:
            raise W2Error('E_TYPE','quantity belongs to a different object class',field)
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value):
            raise W2Error("E_INPUT_BINDING", "numeric evidence binding required", field)
        matches = [m for m in NUMBER.finditer(quote) if float(m.group().replace(",", "")) == value]
        matches = [m for m in matches if re.match(r"\s*" + re.escape(unit) + r"(?![A-Za-z])", quote[m.end():])]
        if not matches:
            raise W2Error("E_INPUT_BINDING", "raw value or original unit differs from quote", field)
        if not re.search(ANCHORS[kind], quote, re.I):
            raise W2Error("E_TYPE", "semantic quantity label differs from quote", field)
        # Existence of the number is insufficient: the nearest quantity label
        # must identify that number, including multi-value source sentences.
        if kind in LABEL_GROUPS:
            correct,other=LABEL_GROUPS[kind]
            def last(pattern,prefix):
                values=list(re.finditer(pattern,prefix,re.I))
                return values[-1].start() if values else -1
            if not any(last(correct,quote[:m.start()])>=0 and last(correct,quote[:m.start()])>last(other,quote[:m.start()]) for m in matches):
                raise W2Error('E_TYPE','numeric value belongs to another semantic quantity',field)
        if kind=='position' and not any(re.search(r'(?:position(?:ed)?|located|距|位置)[^\d]*$',quote[:m.start()],re.I) or
                                            re.match(r'\s*'+re.escape(unit)+r'\s+from\b',quote[m.end():],re.I) for m in matches):
            raise W2Error('E_TYPE','numeric value is not the stated load position',field)
        # C and C0 often occur in the same sentence: inspect the nearest label.
        if kind in ("static_capacity", "dynamic_capacity"):
            mark = "C0" if kind == "static_capacity" else "C"
            if not any(re.search(r"\b" + mark + r"\s*=\s*$", quote[:m.start()], re.I) or
                       re.search(("static" if mark == "C0" else "dynamic") + r"\s+(?:load\s+)?(?:rating|capacity)\s*(?:C0?|=|\s)*$", quote[:m.start()], re.I)
                       for m in matches):
                raise W2Error("E_TYPE", "capacity value belongs to a different label", field)
        if kind == "shaft_speed" and re.search(r"output|输出", " ".join(self.spans[s]["text"] for s in obj["evidence_spans"]), re.I):
            if re.search(r"motor|电机", quote, re.I) and not re.search(r"output.{0,30}(?:rpm|r/min)|输出轴.{0,15}转速", quote, re.I):
                raise W2Error("E_MISSING", "motor speed is not unprovided output shaft speed", field)
        certificate = self.certificates.get(field)
        identity = digest({k: item[k] for k in item})
        if certificate is not None and certificate != identity:
            raise W2Error("E_INPUT_BINDING", "reviewed object binding changed", field)
        # Different labeled bearing loads cannot be exchanged just because units match.
        evidence = " ".join(self.spans[s]["text"] for s in obj["evidence_spans"])
        labels = re.findall(r"\bbearing\s+([AB])\b", quote, re.I)
        object_labels = re.findall(r"\bbearing\s+([AB])\b", evidence, re.I)
        if labels and object_labels and not set(x.upper() for x in labels) <= set(x.upper() for x in object_labels):
            raise W2Error("E_INPUT_BINDING", "input belongs to another bearing", field)
        converted = normalize_quantities(value, unit)
        if converted["unit"] != TYPES[kind]:
            raise W2Error("E_UNIT", "unit does not match quantity type", field)
        return quantity(converted["value"], converted["unit"], kind, object_id=item["object_id"],
                        source_refs=[item["source_span_id"]], conditions=[])


def _check_structure(spec):
    """Bad evidence must never conceal a malformed graph later in a node."""
    declared = set()
    input_ids = {item['input_id'] for item in spec['inputs']}
    for step in spec['steps']:
        sid, rid = step['step_id'], step['relation_id']
        if rid not in RELATIONS:
            raise W2Error('E_SCHEMA','unknown relation shape',sid)
        signature = RELATIONS[rid]
        if set(step['arguments']) != set(signature['inputs']):
            raise W2Error('E_SCHEMA','relation arguments do not match signature',sid)
        if not set(step['output_ids']) <= set(signature['outputs']) or len(step['output_ids']) != len(set(step['output_ids'])):
            raise W2Error('E_SCHEMA','unregistered/duplicate output',sid)
        for ref in step['arguments'].values():
            kind, key = next(iter(ref.items()))
            if kind=='step_ref' and key not in declared:
                raise W2Error('E_SCHEMA','dangling, forward or cyclic step reference',key)
            if kind=='input_ref' and key not in input_ids:
                raise W2Error('E_SCHEMA','unknown input reference',key)
        declared.update(sid+'.'+name for name in step['output_ids'])


def validate_spec(spec, context):
    if context.contract_identity != contract_hash() or context.schema_identity != digest(context.schema):
        raise W2Error('E_SOURCE', 'interface contract/schema changed after context creation')
    validate(spec, context.schema)
    namespaces = [("objects", "object_id"), ("inputs", "input_id"), ("design_choices", "choice_id"),
                  ("scenario_axes", "axis_id"), ("steps", "step_id")]
    for group, key in namespaces:
        ids = [x[key] for x in spec[group]]
        if len(ids) != len(set(ids)) or any(not x or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]*", x) for x in ids):
            raise W2Error("E_SCHEMA", "empty, invalid or duplicate identifiers", group)
    if re.search(r'"(?:case_id|reference_answer|score|judge|evaluations)"|\bq\d{4}\b', __import__('json').dumps(spec), re.I):
        raise W2Error("E_SCHEMA", "evaluation identity/data forbidden in runtime spec")
    _check_structure(spec)
    if spec['branch_id'] not in BRANCH_RELATIONS:
        raise W2Error('E_TYPE', 'unregistered input branch')
    if len(spec['steps']) > LIMITS['declared_nodes']:
        raise W2Error('E_LIMIT', 'declared node bound exceeded')
    objects = {x["object_id"]: x for x in spec["objects"]}
    object_errors = {}
    for obj in objects.values():
        try:
            if not obj["evidence_spans"] or any(s not in context.spans for s in obj["evidence_spans"]):
                raise W2Error("E_INPUT_BINDING", "invalid object evidence", obj["object_id"])
            evidence = " ".join(context.spans[s]["text"] for s in obj["evidence_spans"])
            if not re.search(OBJECT_ANCHORS[obj["object_type"]], evidence, re.I):
                raise W2Error("E_TYPE", "object type not supported by its evidence", obj["object_id"])
        except W2Error as exc:
            object_errors[obj['object_id']] = exc.as_dict()
    if not any(o["object_type"] == "single_row_deep_groove" for o in objects.values()):
        raise W2Error("E_TYPE", "deep-groove ball object required")
    if spec['skill_id'] != SKILL_ID:
        raise W2Error('E_SOURCE','unapproved skill version')
    if context.expected_outputs is None:
        # Execution of partial calculations remains useful; it cannot establish READY.
        warnings = ["DELIVERABLE_COVERAGE_NOT_INDEPENDENTLY_REVIEWED"]
    elif set(spec["requested_outputs"]) != set(context.expected_outputs):
        raise W2Error("E_MISSING", "requested outputs differ from independent preflight inventory")
    else:
        warnings = []
    if spec["design_choices"]:
        raise W2Error("E_TYPE", "first given-capacity package has no design-choice branch")
    inputs, input_errors = {}, {}
    for item in spec["inputs"]:
        try:
            if item['object_id'] in object_errors:
                error = object_errors[item['object_id']]
                raise W2Error(error['code'], 'owning object failed evidence binding: '+error['message'], item['input_id'])
            inputs[item["input_id"]] = context.bound_input(item, objects)
        except W2Error as exc:
            input_errors[item["input_id"]] = exc.as_dict()
    axes = []
    for axis in spec["scenario_axes"]:
        if not axis["basis_spans"] or any(s not in context.spans for s in axis["basis_spans"]):
            raise W2Error("E_INPUT_BINDING", "scenario basis absent")
        values = axis["values"]
        if len(set(values)) != len(values) or any(v not in ("positive", "negative", "midpoint", "numeric") for v in values):
            raise W2Error("E_TYPE", "unapproved physical scenario")
        axes.append([(axis["axis_id"], v) for v in values])
    if spec['branch_id']=='two_supports_single_helical_gear':
        if not any(set(a['values'])=={'positive','negative'} for a in spec['scenario_axes']):
            raise W2Error('E_MISSING','unspecified gear couple direction requires both signed scenarios')
        positions=[q['value'] for q in inputs.values() if q['quantity_type']=='position']
        lengths=[q['value'] for q in inputs.values() if q['quantity_type']=='span']
        if re.search(r'midway|midpoint',context.question,re.I) and positions and lengths and any(abs(a-L/2)>1e-12 for a in positions for L in lengths):
            if not any(set(a['values'])=={'numeric','midpoint'} for a in spec['scenario_axes']):
                raise W2Error('E_MISSING','conflicting midpoint wording requires both numeric and midpoint geometry')
    scenarios = [dict(items) for items in itertools.product(*axes)] if axes else [{}]
    if len(scenarios) > LIMITS['scenarios'] or len(scenarios) * len(spec["steps"]) > LIMITS['expanded_nodes']:
        raise W2Error("E_LIMIT", "scenario/node bound exceeded")
    declared, errors, origins = {}, {}, {}
    for step in spec["steps"]:
        sid, rid = step["step_id"], step["relation_id"]
        try:
            if rid not in RELATIONS:
                raise W2Error("E_TYPE", "unregistered relation", rid)
            signature = RELATIONS[rid]
            if rid not in BRANCH_RELATIONS[spec['branch_id']]:
                raise W2Error('E_TYPE', 'relation outside its input branch', sid)
            if set(step["arguments"]) != set(signature["inputs"]):
                raise W2Error("E_SCHEMA", "relation arguments do not match signature", sid)
            if not set(step["output_ids"]) <= set(signature["outputs"]) or len(set(step["output_ids"])) != len(step["output_ids"]):
                raise W2Error("E_SCHEMA", "unregistered/duplicate output", sid)
            for name, ref in step["arguments"].items():
                kind, key = next(iter(ref.items()))
                expected = signature["inputs"][name]
                if kind == "step_ref":
                    if key not in declared:
                        raise W2Error("E_SCHEMA", "dangling, forward or cyclic step reference", key)
                    actual = declared[key]
                elif kind == "input_ref":
                    if key not in inputs:
                        if key in input_errors:
                            raise W2Error(**{k:v for k,v in input_errors[key].items() if k in ('code','message','field')})
                        raise W2Error("E_SCHEMA", "unknown input reference", key)
                    actual = inputs[key]["quantity_type"]
                elif kind in ("resource_ref", "constant_ref"):
                    q = context.resource(key) if kind == "resource_ref" else context.constants.get(key)
                    if not q:
                        raise W2Error("E_SOURCE", "unapproved constant", key)
                    actual = q["quantity_type"]
                    if rid=='lookup_coefficients' and name=='table' and 'question_coefficient_table' in context.resources and key!='question_coefficient_table':
                        raise W2Error('E_SOURCE','original question table takes precedence over generic coefficients')
                elif kind == "scenario_ref":
                    axis = next((a for a in spec["scenario_axes"] if a["axis_id"] == key), None)
                    if not axis or not set(axis["values"]) <= set(signature["enums"].get(name, [])):
                        raise W2Error("E_TYPE", "scenario enum not allowed for argument", name)
                    actual = expected
                elif kind == "enum":
                    if key not in signature["enums"].get(name, []):
                        raise W2Error("E_TYPE", "unapproved enum", name)
                    # A direction can be conditional; locating A/B needs actual evidence.
                    if expected == "locating_end":
                        label = "left" if key == "A" else "right"
                        clauses=re.split(r'(?<=[.;])\s+|\bwhile\b|\bwhereas\b',context.question,flags=re.I)
                        evidence=any(re.search(r'(?:'+label+r' bearing|bearing '+key+r'\b)[^.!?;]{0,120}(?:locating|fixed|carries? (?:the |both radial and )?axial|takes? the axial)',clause,re.I)
                                     for clause in clauses)
                        if not evidence:
                            raise W2Error("E_MISSING", "locating end not evidenced", name)
                    actual = expected
                else:
                    raise W2Error("E_TYPE", "unsupported reference kind", kind)
                if actual != expected and actual not in COMPATIBLE.get(expected, set()):
                    raise W2Error("E_TYPE", f"expected {expected}, got {actual}", name)
                if rid=='axial_force_couple' and name=='direction' and kind!='scenario_ref':
                    raise W2Error('E_MISSING','both declared signed scenarios must actually drive the couple')
                if rid == "shaft_reactions_two_supports" and spec["branch_id"] == "two_supports_single_helical_gear" and name in ("Fy", "Fz", "My", "Mz"):
                    required = ("gear_forces." if name in ("Fy", "Fz") else "axial_force_couple.") + name
                    if kind != "step_ref" or origins.get(key) != required:
                        raise W2Error("E_INVARIANT", "missing or swapped independently required gear load component", name)
        except W2Error as exc:
            if exc.code == "E_SCHEMA":
                raise
            errors[sid] = exc.as_dict()
        if rid in RELATIONS:
            for output in step["output_ids"]:
                if output in RELATIONS[rid]["outputs"]:
                    declared[sid + "." + output] = RELATIONS[rid]["outputs"][output]
                    origins[sid + "." + output] = rid + "." + output
    return {"inputs": inputs, "input_errors": input_errors, "object_errors": object_errors, "node_errors": errors,
            "scenarios": scenarios, "warnings": warnings}
