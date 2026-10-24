"""One bounded DAG; partial failures preserve independent successful results."""
from __future__ import annotations
import copy
import json
import time
from . import VERSION
from .contract import LIMITS
from ..common import W2Error, digest, quantity, write
from ..kernels import FUNCTIONS
from ..registry import RELATIONS, TYPES
from .validation import validate_spec


def execute_plan(spec, context, *, trace_path=None, timeout=LIMITS['local_seconds'], max_bytes=LIMITS['return_utf8_bytes']):
    started = time.monotonic()
    packet = {"status": "ERROR", "tool_version": VERSION, "input_hash": None,
              "results": [], "checks": [], "source_refs": [], "warnings": [], "blocked_outputs": []}
    try:
        try:packet['input_hash']=digest(spec)
        except (TypeError,ValueError) as exc:raise W2Error('E_SCHEMA','non-JSON or nonfinite plan') from exc
        validated = validate_spec(spec, context)
    except W2Error as exc:
        packet["error"] = exc.as_dict()
        packet['checks'] = [{'name':'global_plan_validation','status':'ERROR','error':exc.as_dict()}]
        packet['blocked_outputs'] = [{'output':'ALL','code':exc.code}]
        packet['elapsed_seconds'] = time.monotonic()-started
        if trace_path: write(trace_path, packet)
        return packet
    packet["warnings"].extend(validated["warnings"])
    if context.load_inventory is None:
        packet["warnings"].append("INPUT_LOAD_COVERAGE_NOT_INDEPENDENTLY_REVIEWED")
    for number, scenario in enumerate(validated["scenarios"], 1):
        scenario_id, outputs = f"scenario_{number}", {}
        for step in spec["steps"]:
            sid, rid = step["step_id"], step["relation_id"]
            node = {"step_id": sid, "scenario_id": scenario_id, "conditions": scenario,
                    "relation_id": rid, "status": "ERROR", "input_hash": None, "outputs": {}}
            try:
                if time.monotonic() - started >= timeout:
                    raise W2Error("E_LIMIT", "local tool deadline exceeded")
                if sid in validated["node_errors"]:
                    e = validated["node_errors"][sid]
                    raise W2Error(e["code"], e["message"], e["field"])
                arguments, provenance = {}, set()
                for name, ref in step["arguments"].items():
                    kind, key = next(iter(ref.items()))
                    if kind == "input_ref":
                        q = validated["inputs"][key]
                        provenance.add(key)
                        provenance.add('quantity:'+q['quantity_type'])
                    elif kind == "step_ref":
                        if key not in outputs:
                            node["status"] = "BLOCKED"
                            raise W2Error("E_MISSING", "upstream output failed", key)
                        q = outputs[key]
                        provenance.update(q.get("input_lineage", []))
                    elif kind == "resource_ref":
                        q = context.resource(key)
                        packet["source_refs"].append(key)
                    elif kind == "constant_ref":
                        q = context.constants[key]
                    else:
                        arguments[name] = scenario[key] if kind == "scenario_ref" else key
                        continue
                    arguments[name] = q["value"]
                node["input_hash"] = digest(arguments)
                node["arguments"] = arguments
                # This is a separate inventory, not the model's self-reported check.
                if rid in ("shaft_reactions_two_supports", "check_equilibrium") and context.load_inventory is not None:
                    missing = set(context.load_inventory) - provenance
                    if missing:
                        raise W2Error("E_INVARIANT", "omitted independent load inputs: " + str(sorted(missing)))
                raw = FUNCTIONS[rid](**arguments)
                if time.monotonic() - started > timeout:
                    raise W2Error("E_LIMIT", "local tool deadline exceeded")
                for output_id in step["output_ids"]:
                    kind = RELATIONS[rid]["outputs"][output_id]
                    result = quantity(raw[output_id], TYPES[kind], kind,
                                      source_refs=RELATIONS[rid]["sources"], conditions=scenario,
                                      input_lineage=sorted(provenance), scenario_id=scenario_id)
                    outputs[sid + "." + output_id] = result
                    node["outputs"][output_id] = result
                node["status"] = "OK"
            except W2Error as exc:
                node["error"] = exc.as_dict()
                packet["blocked_outputs"].extend({"scenario_id": scenario_id, "output": sid + "." + o,
                                                   "code": exc.code} for o in step["output_ids"])
            except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
                node["error"] = {"code": "E_RANGE", "message": str(exc)}
                packet["blocked_outputs"].extend({"scenario_id": scenario_id, "output": sid + "." + o,
                                                   "code": "E_RANGE"} for o in step["output_ids"])
            packet["results"].append(node)
    packet["source_refs"] = sorted(set(packet["source_refs"]))
    ok = sum(r["status"] == "OK" for r in packet["results"])
    packet["status"] = "OK" if ok == len(packet["results"]) and ok else "PARTIAL" if ok else "ERROR"
    if packet['status']=='OK' and (validated['object_errors'] or validated['input_errors']):
        packet['status']='PARTIAL'
    packet["checks"] = [{"name": "shape_and_reference_graph", "status": "OK"},
                         {'name':'object_evidence','status':'ERROR' if validated['object_errors'] else 'OK',
                          'errors':validated['object_errors']},
                         {"name": "input_evidence", "status": "ERROR" if validated["input_errors"] else "OK",
                          "errors": validated["input_errors"]},
                         {"name": "independent_load_inventory", "status": "REVIEW_REQUIRED" if context.load_inventory is None else "CHECKED_AT_CONSUMERS"},
                         {"name": "requested_output_coverage", "status": "REVIEW_REQUIRED" if context.expected_outputs is None else "MATCHED_PREFLIGHT"}]
    packet["elapsed_seconds"] = time.monotonic() - started
    if trace_path:
        write(trace_path, packet)
    # Keep full argument/provenance records in the trace and return the bounded
    # numerical contract. This is a projection, never truncation of conditions.
    packet['scenario_definitions'] = {f'scenario_{i}': s for i,s in enumerate(validated['scenarios'],1)}
    packet['step_metadata'] = {s['step_id']: {'relation_id':s['relation_id'],
                                            'source_refs': RELATIONS[s['relation_id']]['sources']}
                               for s in spec['steps'] if s['relation_id'] in RELATIONS}
    for node in packet["results"]:
        node.pop("arguments", None)
        node.pop("input_hash", None)
        node.pop('relation_id',None)
        node.pop('conditions',None)
        for q in node["outputs"].values():
            q.pop("input_lineage", None)
            q.pop("scenario_id", None)
            q.pop('quantity_type',None)
            q.pop('source_refs',None)
            q['conditions'] = {'scenario_ref': node['scenario_id']}
    if len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) > max_bytes:
        # Preserve the full trace on disk; never truncate trailing conditions.
        return {"status": "ERROR", "tool_version": VERSION, "input_hash": packet["input_hash"],
                "results": [], "checks": [], "source_refs": packet["source_refs"],
                "warnings": ["Full local trace retained; result envelope exceeded fixed limit"],
                "blocked_outputs": [{"output": "ALL", "code": "E_LIMIT"}],
                "error": {"code": "E_LIMIT", "message": "tool result exceeds UTF-8 byte bound"}}
    return packet


def check_deliverables(answer, tool_result, expected_outputs=None):
    """Record explicit contradictions; unrestricted prose still needs root review.

    An explicit `step.output = number` is mechanically checkable. Absence of that
    notation is never represented as an automatic engineering pass.
    """
    import re
    mismatches = []
    for node in tool_result.get("results", []):
        if node["status"] != "OK":
            continue
        for key, q in node["outputs"].items():
            if not isinstance(q["value"], (int, float)):
                continue
            label = node["step_id"] + "." + key
            if len({r["scenario_id"] for r in tool_result.get("results", [])}) > 1:
                label = node["scenario_id"] + "." + label
            for match in re.finditer(re.escape(label) + r"\s*=\s*([-+]?\d+(?:\.\d+)?)", answer):
                actual = float(match[1])
                if abs(actual - q["value"]) > max(1e-6, abs(q["value"]) * .005):
                    mismatches.append({"code": "E_FINAL_MISMATCH", "label": label,
                                       "scenario_id": node["scenario_id"], "written": actual, "tool": q["value"]})
    return {"status": "ERROR" if mismatches else "REVIEW_REQUIRED", "mismatches": mismatches,
            "expected_outputs": expected_outputs, "answer_modified": False,
            "engineering_content_review": "PENDING", "score": None}
