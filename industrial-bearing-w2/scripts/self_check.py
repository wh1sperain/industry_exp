"""Independent synthetic fixture; local checks only, no network/model calls."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run import REFS, shared_assets
from bearing_w2.common import read
from bearing_w2.interface_revision.contract import build_schema, contract_hash
from bearing_w2.interface_revision.validation import Context
from bearing_w2.interface_revision.execution import execute_plan


def main():
    question=('A deep groove ball bearing has dynamic load rating C = 30 kN and static load rating C0 = 20 kN.\n'
              'The bearing operates at 1000 rpm with radial load of 3000 N and axial load of 100 N.\n')
    def inp(key,kind,value,unit,span,quote):
        return dict(input_id=key,object_id='bearing',quantity_type=kind,value=value,unit=unit,source_span_id=span,quote=quote)
    def i(key):return {'input_ref':key}
    def s(key):return {'step_ref':key}
    spec=dict(schema_version='1.0.0',skill_id='given-capacity-v1',branch_id='direct_bearing_loads',
              objects=[dict(object_id='bearing',object_type='single_row_deep_groove',evidence_spans=['s0001'])],
              requested_outputs=['basic_life','static_safety'],design_choices=[],missing_inputs=[],scenario_axes=[],
              inputs=[inp('C','dynamic_capacity',30,'kN','s0001','dynamic load rating C = 30 kN'),
                      inp('C0','static_capacity',20,'kN','s0001','static load rating C0 = 20 kN'),
                      inp('n','shaft_speed',1000,'rpm','s0002','operates at 1000 rpm'),
                      inp('Fr','radial_load',3000,'N','s0002','radial load of 3000 N'),
                      inp('Fa','axial_load',100,'N','s0002','axial load of 100 N')],steps=[
                dict(step_id='table',relation_id='lookup_coefficients',arguments={'axial_load':i('Fa'),'static_capacity':i('C0'),'table':{'resource_ref':'generic_Fa_C0_table'}},output_ids=['e','X','Y']),
                dict(step_id='dynamic',relation_id='equivalent_dynamic_load',arguments={'radial_load':i('Fr'),'axial_load':i('Fa'),'rotation_factor':{'resource_ref':'rotation_inner'},'e':s('table.e'),'X':s('table.X'),'Y':s('table.Y'),'load_factor':{'resource_ref':'load_factor_unity'}},output_ids=['P']),
                dict(step_id='life',relation_id='bearing_life_hours',arguments={'dynamic_capacity':i('C'),'equivalent_load':s('dynamic.P'),'speed':i('n')},output_ids=['L10h']),
                dict(step_id='static',relation_id='equivalent_static_load',arguments={'radial_load':i('Fr'),'axial_load':i('Fa'),'static_capacity':i('C0')},output_ids=['P0','s0'])])
    schema=build_schema(read(REFS/'problem-spec-base.json'),spec['branch_id'])
    context=Context(question,schema,read(REFS/'resources.json'),expected_outputs=spec['requested_outputs'])
    result=execute_plan(spec,context)
    assert result['status']=='OK',result
    assert abs(result['results'][2]['outputs']['L10h']['value']-16666.666666666668)<1e-8
    assert result['results'][3]['outputs']['P0']['value']==3000
    bad=copy.deepcopy(spec)
    bad['objects'].append(dict(object_id='aux',object_type='shaft',evidence_spans=['s0002']))
    bad['inputs'][2]['object_id']='aux';before=copy.deepcopy(bad)
    partial=execute_plan(bad,context)
    assert partial['status']=='PARTIAL' and [n['status'] for n in partial['results']]==['OK','OK','ERROR','OK']
    assert bad==before
    malformed=copy.deepcopy(spec);malformed['steps'][2]['arguments']['equivalent_load']={'step_ref':'future.P'}
    assert execute_plan(malformed,context)['error']['code']=='E_SCHEMA'
    exposed=json.loads(shared_assets(spec['branch_id'])['interface'])
    assert exposed['problem_spec_schema']==schema
    from bearing_w2.common import digest
    assert digest(exposed['public_execution_contract'])==contract_hash()
    print(json.dumps({'status':'PASS','checks':6,'model_calls':0,'network_calls':0}))


if __name__=='__main__':main()
