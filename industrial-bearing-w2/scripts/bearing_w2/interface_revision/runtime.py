"""Exactly two semantic stages. Failed transport waits instead of resending."""
from __future__ import annotations
import copy
from pathlib import Path
from ..common import W2Error, digest, read, write, spans
from .validation import parse_plan
from .execution import execute_plan, check_deliverables
from .contract import contract_hash
from . import VERSION


def request_for_stage(original, question, assets, arm, phase, *, plan_response=None, tool_result=None):
    if arm not in ("G2", "K2") or phase not in ("plan", "final"):
        raise W2Error("E_SCHEMA", "unregistered arm or phase")
    p = {k: copy.deepcopy(v) for k, v in original.items() if k != "messages"}
    # Start at the raw pre-S1 question; no disabled-tool instructions survive.
    instructions = assets["planner" if phase == "plan" else "finalizer"]
    if phase=='final' and assets.get('answer_format'):
        instructions += '\n'+assets['answer_format']
    body = assets["facts"] + "\n" + assets["interface"]
    body += "\n原题段号（宿主生成）：\n" + __import__('json').dumps(spans(question), ensure_ascii=False)
    if arm == "K2":
        body += "\n" + assets["skill"]
    p["messages"] = [{"role": "system", "content": instructions + "\n" + body},
                     {"role": "user", "content": question}]
    if phase == "final":
        p["messages"].append({"role": "assistant", "content": plan_response})
        p["messages"].append({"role": "user", "content": "真实宿主执行结果：\n" +
                              __import__('json').dumps(tool_result, ensure_ascii=False)})
    return p


def cache_key(request, versions, phase, tool_result=None):
    return digest({"request": request, "versions": versions, "phase": phase,
                   "protocol": "W2/2/no-repair/"+VERSION, "contract":contract_hash(), "tool_result": tool_result})


def run_w2(episode_id, original, question, context, assets, arm, call, ledger, run_directory, *, versions):
    """`call` has the existing host.call(provider,id,payload,stage) signature.

    `ledger` consumes an already atomically reserved episode. Tests use a mock;
    real execution requires an explicit live permit and the shared old ledger.
    """
    # Reject a model-visible contract that differs from actual validation BEFORE
    # checking reservations or dispatching. Both arms use these exact assets.
    try:
        exposed = __import__('json').loads(assets['interface'])
    except (ValueError,KeyError,TypeError) as exc:
        raise W2Error('E_SOURCE','missing public interface contract') from exc
    if digest(exposed.get('public_execution_contract')) != context.contract_identity or digest(exposed.get('problem_spec_schema')) != context.schema_identity:
        raise W2Error('E_SOURCE','public interface and runtime context differ')
    if context.contract_identity != contract_hash() or digest(context.schema) != context.schema_identity:
        raise W2Error('E_SOURCE','context interface changed')
    versions = {**versions,'engineering_runtime':VERSION,'public_contract':contract_hash(),
                'public_schema':context.schema_identity}
    target = Path(run_directory) / episode_id
    state_path = target / "state.json"
    identity = digest({"original": original, "question": question, "assets": assets,
                       "arm": arm, "versions": versions, "resources": context.resource_identities,
                       'schema':context.schema_identity,'contract':context.contract_identity})
    if state_path.exists():
        state = read(state_path)
        if state.get("execution_identity") != identity:
            raise W2Error("E_SOURCE", "existing episode has a different request or frozen version")
        if state["status"] == "COMPLETE":
            return state
        # An interrupted send is never assumed not to have reached the endpoint.
        return {**state, "status": "WAIT_PROVIDER_RECONCILIATION", "automatic_resend": False}
    state = {"status": "RESERVED", "semantic_calls": 0, "tool_batches": 0, "score": None,
             "answer": None, "usage": [], "episode_id": episode_id, "arm": arm,
             "execution_identity": identity}
    ledger.assert_episode_reserved(episode_id, qwen_calls=2, grades=1)
    write(state_path, state)
    plan_raw, result = None, None
    for index, phase in enumerate(("plan", "final"), 1):
        payload = request_for_stage(original, question, assets, arm, phase,
                                    plan_response=plan_raw, tool_result=result)
        logical_id = f"{episode_id}_{phase}"
        key = cache_key(payload, versions, phase, result)
        write(target / f"{phase}-request.json", payload)
        write(target / f"{phase}-identity.json", {"cache_key": key, "versions": versions})
        ledger.begin_request(logical_id, payload)
        state.update(status="IN_FLIGHT", semantic_calls=index)
        write(state_path, state)
        try:
            response = call("qwen", logical_id, copy.deepcopy(payload), "W2_" + phase)
        except Exception as exc:
            ledger.unknown(logical_id)
            state.update(status="WAIT_PROVIDER_RECONCILIATION", error=type(exc).__name__, automatic_resend=False)
            write(state_path, state)
            return state
        write(target / f"{phase}-response.json", response)
        usage = response.get("usage", {})
        ledger.finish_request(logical_id, usage, response.get("status"))
        state["usage"].append(usage)
        if response.get("status") != "complete":
            state.update(status="WAIT_PROVIDER_RECONCILIATION", automatic_resend=False)
            write(state_path, state)
            return state
        raw = response["response"]["content"]
        if phase == "plan":
            plan_raw = raw
            try:
                spec = parse_plan(raw)
                write(target / "plan.json", spec)
                result = execute_plan(spec, context, trace_path=target / "tool-trace.json")
                state["tool_batches"] = 1
                state['tool_elapsed_seconds']=result.get('elapsed_seconds',0)
            except W2Error as exc:
                result = {"status": "ERROR", "tool_version": versions.get("code"), "input_hash": digest(raw),
                          "results": [], "checks": [], "source_refs": [], "warnings": [],
                          "blocked_outputs": [{"output": "ALL", "code": exc.code}], "error": exc.as_dict()}
            write(target / "tool-result.json", result)
        else:
            state.update(status="COMPLETE", answer=raw,
                         finish_reason=response["response"].get("finish_reason"),
                         answer_sha256=digest(raw.encode("utf-8")),
                         delivery=check_deliverables(raw, result, context.expected_outputs))
            if response["response"].get("finish_reason") not in (None, "stop"):
                state["delivery"]["status"] = "ERROR"
                state["delivery"]["finish_error"] = "truncated_or_nonfinal"
            try:
                envelope=__import__('json').loads(raw)
            except (ValueError,TypeError):
                envelope={}
            if not raw.strip() or isinstance(envelope,dict) and (envelope.get('action')=='CALL_TOOLS' or 'schema_version' in envelope and 'steps' in envelope):
                state["delivery"]["status"] = "ERROR"
                state["delivery"]["finish_error"] = "tool_request_in_final"
        write(state_path, state)
    return state
