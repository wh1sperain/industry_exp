---
name: industrial-bearing-w2
description: Calculate given-capacity single-row deep-groove bearing loads, life and static safety with source-bound inputs and a bounded dependency graph. Use for direct bearing loads, one centerline transverse load or one helical gear between two supports.
---

Use the supplied original question, reusable engineering relations and approved source records. The model chooses the physical model and gives the final engineering answer; scripts validate provenance and perform numerical calculations.

## Scope and source preparation

Check [references/scope.json](references/scope.json) before planning. This package covers given dynamic/static capacities, steady loads and the three registered branches. Catalog selection, other bearing types, overhung/multiple-gear shafts, unknown output speed and accumulated-damage remaining life require another model or additional evidence.

Read [references/runtime_facts.json](references/runtime_facts.json) for formulas, source-bound coefficient/reliability resources and condition policies. Source locations are indexed in [references/sources.json](references/sources.json). Question-given tables take precedence; a newly transcribed table must be independently checked and registered with its version and content hash.

## Build one complete plan

1. List every requested output, available inputs and genuinely missing quantities. Preserve given values and adjacent units verbatim in source quotes.
2. Use the exact Skill identifier and input ownership rules in [references/execution-contract.json](references/execution-contract.json). For directly given bearing loads, the bearing object can own its operating speed under `shaft_speed`; an auxiliary shaft object is unnecessary. Declare only objects supported by the cited original text.
3. Select the branch schema in `references/schemas/`: `direct_bearing_loads.json`, `two_supports_single_transverse_load.json` or `two_supports_single_helical_gear.json`.
4. Represent all known dependencies in one DAG. Use registered output names and qualified `step_id.output_id` references; never copy derived values into new given inputs.
5. For supported shafts, calculate both transverse planes, required axial-offset couples and locating/floating loads. A centerline pump force does not gain a moment arm from shaft diameter. Preserve unresolved sign or geometry cases separately.
6. Use the actual coefficient-table index, compare dynamic-load branches, calculate life with the analyzed object's speed, then apply explicitly named reliability factors. Calculate static safety from actual loads; report the result conditionally when no acceptance threshold is specified.

The public contract, schemas and runtime validators share the same policy definitions. `references/problem-spec-base.json` defines structure; branch membership, evidence and type compatibility are semantic checks. Do not add descriptive geometry or reliability-percent fields as unsupported numeric input types.

## Execute and interpret the result

Python 3.11+ standard library is sufficient. From this Skill directory:

```text
python scripts/run.py spans --question question.txt
python scripts/run.py contract --branch direct_bearing_loads
python scripts/run.py execute --question question.txt --plan plan.json --requested-output basic_life --requested-output static_safety
```

Match `--requested-output` to the full inventory independently identified from the original question. If omitted, coverage remains explicitly unreviewed. Use `--resources` for a separately approved source registry; the default registry contains reusable coefficient and reliability tables, not bearing catalog capacities.

Malformed structure/references reject the batch. A failed object or input blocks its dependent calculations; independent nodes continue. A `PARTIAL` result includes successful values and all local errors. The host never silently removes an object, rebinds an input or substitutes a number. Report failed and unresolved calculations honestly.

The bounded W2 integration in `scripts/bearing_w2/interface_revision/runtime.py` accepts an externally authorized model transport and prepaid ledger. It performs exactly two semantic calls: plan, one real DAG execution, final answer. A failed plan still goes to the final call; there is no repair call. Unknown transport state is retained without automatic resend. This package has no API credentials or automatic paid launcher.

For a host integration, obtain common G2/K2 assets with `python scripts/run.py assets --branch direct_bearing_loads`. Both arms receive identical facts, tools and interface; only K2 adds the task procedure. Bind cache identity to the complete request, contract/schema, code/resource versions and real tool results.

## Final answer and local checks

Complete every requested subquestion with formulas, values, units, physical conditions and an engineering conclusion. Tool success verifies only the executed calculation. Do not claim unexecuted values were verified or invent a static threshold, catalog value or missing shaft speed.

Run `python scripts/self_check.py` to check the standalone package without network or model calls. The included checks establish local interface behavior; model performance and population-level acceptance require separate authorized evaluation.
