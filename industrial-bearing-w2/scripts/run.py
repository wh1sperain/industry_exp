"""Local source-bound tools. No API client, credentials or experiment dispatch."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))

from bearing_w2.common import read, spans
from bearing_w2.interface_revision.contract import public_contract, build_schema, BRANCH_RELATIONS
from bearing_w2.interface_revision.validation import Context
from bearing_w2.interface_revision.execution import execute_plan

SKILL = Path(__file__).resolve().parents[1]
REFS = SKILL/'references'


def shared_assets(branch):
    schema=build_schema(read(REFS/'problem-spec-base.json'),branch)
    prompts=read(REFS/'prompts.json')
    return {**prompts,'facts':json.dumps(read(REFS/'runtime_facts.json'),ensure_ascii=False),
            'interface':json.dumps({'problem_spec_schema':schema,'public_execution_contract':public_contract()},ensure_ascii=False),
            'skill':(SKILL/'SKILL.md').read_text(encoding='utf-8')}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ['contract','assets']:
        p=sub.add_parser(action);p.add_argument('--branch',required=True,choices=list(BRANCH_RELATIONS))
    p=sub.add_parser('spans');p.add_argument('--question',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--question',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--resources',type=Path,default=REFS/'resources.json')
    p.add_argument('--requested-output',action='append',dest='outputs')
    p.add_argument('--load-source',action='append',dest='load_sources')
    p.add_argument('--trace',type=Path)
    args=parser.parse_args()
    if args.action=='assets':result=shared_assets(args.branch)
    elif args.action=='contract':
        result={'public_execution_contract':public_contract(),
                'problem_spec_schema':build_schema(read(REFS/'problem-spec-base.json'),args.branch)}
    else:
        # Preserve original CR/LF and Unicode offsets when making source spans.
        question=args.question.read_bytes().decode('utf-8')
        if args.action=='spans':result=spans(question)
        else:
            plan=read(args.plan)
            schema=build_schema(read(REFS/'problem-spec-base.json'),plan['branch_id'])
            context=Context(question,schema,read(args.resources),expected_outputs=args.outputs,
                            source_load_inventory=args.load_sources)
            result=execute_plan(plan,context,trace_path=args.trace)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
