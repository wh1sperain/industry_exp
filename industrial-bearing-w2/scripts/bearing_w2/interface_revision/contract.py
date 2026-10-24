"""One policy source for public instructions, schemas and runtime checks."""
from __future__ import annotations
import copy
import re

from ..common import digest
from ..kernels import UNITS
from ..registry import RELATIONS, TYPES, COMPATIBLE
from . import VERSION

NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\d.])")
ANCHORS = {
    'dynamic_capacity':r'(?:\bC(?!0)\s*=|dynamic\s+(?:load\s+)?(?:rating|capacity)|额定动载|动额定)',
    'static_capacity':r'(?:\bC0\s*=|static\s+(?:load\s+)?(?:rating|capacity)|额定静载|静额定)',
    'radial_load':r'radial|Fr|径向','axial_load':r'axial|thrust|Fa|轴向',
    'shaft_speed':r'rpm|r/min|rev/min|转速','power':r'kW|watt|功率',
    'speed_limit':r'limit speed|限速|极限转速','diameter':r'diameter|直径',
    'span':r'span|spaced|跨度|间距','position':r'from|located|position|距|位置',
    'normal_pressure_angle':r'normal pressure angle|法向压力角','helix_angle':r'helix angle|螺旋角',
    'target_hours':r'life|operate|运行|寿命|hours','rotation_factor':r'rotation|旋转',
    'load_factor':r'load factor|shock factor|载荷系数|冲击系数','reliability_factor':r'a1|reliability|可靠度',
}
OBJECT_ANCHORS = {'single_row_deep_groove':r'deep.groove.*ball|深沟球',
                  'single_helical_gear':r'helical|pinion|斜齿轮','shaft':r'shaft|轴',
                  'pump_transverse_load':r'pump|impeller|泵','bearing_support':r'bearing|轴承'}

SKILL_ID = 'given-capacity-v1'
LIMITS = dict(declared_nodes=24, scenario_axes=2, scenarios=4, expanded_nodes=96,
              local_seconds=5, return_utf8_bytes=24576, semantic_calls=2)
CORE_RELATIONS = ['lookup_coefficients','equivalent_dynamic_load','bearing_life_hours',
                  'reliability_life','equivalent_static_load','required_dynamic_rating','check_speed_limit']
BRANCH_RELATIONS = {
    'direct_bearing_loads': CORE_RELATIONS,
    'two_supports_single_transverse_load': CORE_RELATIONS + [
        'transverse_components','shaft_reactions_two_supports','resolve_axial_loads','check_equilibrium'],
    'two_supports_single_helical_gear': CORE_RELATIONS + [
        'gear_forces','axial_force_couple','geometry_position','shaft_reactions_two_supports',
        'resolve_axial_loads','check_equilibrium'],
}
INPUT_OWNERS = {kind: sorted(OBJECT_ANCHORS) for kind in ANCHORS}
INPUT_OWNERS.update(
    dynamic_capacity=['single_row_deep_groove'], static_capacity=['single_row_deep_groove'],
    power=['single_helical_gear','shaft'], diameter=['single_helical_gear'],
    normal_pressure_angle=['single_helical_gear'], helix_angle=['single_helical_gear'],
    span=['shaft'], position=['shaft'])
LABEL_GROUPS = {
    'radial_load': (r'radial|径向|\bFr\b', r'axial|thrust|轴向|\bFa\b'),
    'axial_load': (r'axial|thrust|轴向|\bFa\b', r'radial|径向|\bFr\b'),
    'normal_pressure_angle': (r'normal pressure angle|法向压力角', r'helix angle|螺旋角'),
    'helix_angle': (r'helix angle|螺旋角', r'normal pressure angle|法向压力角'),
    'span': (r'span|spaced|跨度|间距', r'position|located|from the left|位置'),
}


def public_contract():
    """No case IDs, historical scores, reference answers or instance values."""
    return {
        'engineering_revision': VERSION, 'skill_id': SKILL_ID,
        'identity_policy': 'skill_id is exact. Engineering revision is separate host/cache metadata.',
        'limits': copy.deepcopy(LIMITS),
        'objects': {'evidence_regex_case_insensitive': copy.deepcopy(OBJECT_ANCHORS),
                    'evidence_rule': 'Every evidence_spans ID must exist in the original question; its text must support the declared object type. An inferred auxiliary shaft is not required for given bearing loads.',
                    'direct_load_guidance': 'Use the supported bearing object for the bearing operating speed. The existing quantity identifier shaft_speed also represents that speed; it does not require a shaft object. Do not declare unused inferred objects.'},
        'inputs': {'quantity_label_regex_case_insensitive':copy.deepcopy(ANCHORS),
                   'allowed_object_types':copy.deepcopy(INPUT_OWNERS),
                   'nearest_label_groups':copy.deepcopy(LABEL_GROUPS),
                   'quantity_units':copy.deepcopy(TYPES),
                   'allowed_raw_units':list(UNITS),
                   'numeric_binding': 'Copy a numeric value and its adjacent original unit verbatim into a literal quote within source_span_id. Host performs conversion. Nearest matching quantity label must identify this number; C and C0 cannot be exchanged.',
                   'ownership': 'Bearing A/B evidence cannot be swapped. Motor speed cannot substitute for unprovided output-shaft speed. Host-reviewed certificates, when present, bind the exact original input record.',
                   'optional_metadata': 'Only registered quantity types are numeric inputs. Do not add diameter/width/reliability-percent metadata that no requested relation consumes; reliability factors and catalog coefficients use approved resources.'},
        'allowed_relations_by_branch':copy.deepcopy(BRANCH_RELATIONS),
        'relation_signatures':copy.deepcopy(RELATIONS),
        'compatible_quantity_types':{k:sorted(v) for k,v in COMPATIBLE.items()},
        'references': {'step_ref':'step_id.output_id, declared strictly earlier; no aliases or forward/cyclic references',
                       'input_ref':'exact inputs.input_id', 'resource_ref':'exact approved key with source/version/hash/row/field identity',
                       'scenario_ref':'declared axis ID and its approved enum values',
                       'enum':'registered relation argument enum; fixed/locating end additionally needs original-question evidence',
                       'constant_ref':'disabled in the given-capacity revision', 'choice_ref':'disabled; given-capacity scope has no catalog design selection'},
        'source_policy': 'Question coefficient tables take precedence. No guessed e/Y/C/C0/a1 values. Resource quantities and versions must match their frozen identities.',
        'scenario_policy': 'Unspecified gear-couple direction retains both signed cases. Conflicting numeric/midpoint positions retain both geometry cases. No merging mutually exclusive cases.',
        'load_policy': 'Gear support reactions consume both force planes and the axial-offset couple from registered upstream relations. A pump centerline force does not acquire a moment arm from shaft diameter. Independent source load inventory is checked at consumers.',
        'delivery_policy': 'requested_outputs matches the independent inventory. Tool success never proves the whole answer; report all successful values, conditions, failures and truly unknown quantities. No invented static acceptance threshold.',
        'failure_policy': {'global': 'Malformed schema/IDs/references, missing scope object, source-version mismatch of interface, and global scenario/size constraints reject the batch.',
                           'local': 'Object-evidence or numeric-input failures invalidate only owned inputs and their consumers. Failed nodes block descendants. Independent nodes still execute.',
                           'no_repair': 'Host never deletes/rebinds objects, fills numbers or repairs a model plan. W2 remains exactly two semantic calls.',
                           'reporting': 'Any local errors make batch PARTIAL even if unrelated calculations succeed; all diagnostics and blocked outputs are returned.'},
        'same_for_G2_K2': True, 'new_engineering_relations': False,
    }


def contract_hash():
    return digest(public_contract())


def build_schema(base, branch):
    """Structure is strict; semantic domain failures remain local to nodes."""
    if branch not in BRANCH_RELATIONS: raise ValueError('unregistered branch')
    schema = copy.deepcopy(base)
    schema['properties']['skill_id'] = {'const':SKILL_ID}
    schema['properties']['branch_id'] = {'const':branch}
    schema['properties']['design_choices']['maxItems'] = 0
    schema['properties']['steps']['maxItems'] = LIMITS['declared_nodes']
    schema['properties']['scenario_axes']['maxItems'] = LIMITS['scenario_axes']
    schema['properties']['inputs']['items']['properties']['unit'] = {'type':'string','enum':list(UNITS)}
    schema['properties']['objects']['items']['properties']['object_type'] = {'enum':list(OBJECT_ANCHORS)}
    # All registered shapes are public. Branch membership is a semantic node
    # check, so a domain mistake cannot suppress an independent valid node.
    references = base['properties']['steps']['items']['properties']['arguments']['additionalProperties']['oneOf']
    variants = []
    for rid, signature in RELATIONS.items():
        step = copy.deepcopy(base['properties']['steps']['items'])
        step['properties']['relation_id'] = {'const':rid}
        step['properties']['output_ids'] = {'type':'array','minItems':1,'uniqueItems':True,
                                           'items':{'enum':list(signature['outputs'])}}
        arguments = {}
        for name in signature['inputs']:
            allowed = [copy.deepcopy(r) for r in references
                       if not set(r.get('properties',{})) & {'choice_ref','constant_ref','enum'}]
            if name in signature['enums']:
                allowed.append({'type':'object','properties':{'enum':{'enum':signature['enums'][name]}},
                                'required':['enum'],'additionalProperties':False})
            arguments[name] = {'oneOf':allowed}
        step['properties']['arguments'] = {'type':'object','required':list(arguments),
                                          'properties':arguments,'additionalProperties':False}
        variants.append(step)
    schema['properties']['steps']['items'] = {'oneOf':variants}
    return schema
