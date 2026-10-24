"""Reviewable relation signatures shared by the validator and executor."""
from __future__ import annotations

TYPES = {
    "dynamic_capacity": "N", "static_capacity": "N", "radial_load": "N", "axial_load": "N",
    "force": "N", "equivalent_dynamic_load": "N", "equivalent_static_load": "N",
    "shaft_speed": "rpm", "speed_limit": "rpm", "power": "W", "diameter": "m", "span": "m", "position": "m",
    "normal_pressure_angle": "deg", "helix_angle": "deg", "moment": "N*m", "life_hours": "h",
    "target_hours": "h", "reliability_factor": "1", "rotation_factor": "1", "load_factor": "1",
    "coefficient": "1", "safety_factor": "1", "ratio": "1", "coefficient_table": "table",
    "direction": "enum", "locating_end": "enum", "geometry": "enum", "plane": "enum", "report": "json", "label": "text",
}


def relation(inputs, outputs, formula, sources, domain, enums=None):
    return {"inputs": inputs, "outputs": outputs, "formula": formula, "sources": sources,
            "domain": domain, "enums": enums or {}, "error_codes": ["E_TYPE", "E_UNIT", "E_SOURCE", "E_RANGE", "E_MISSING"]}


RELATIONS = {
    "gear_forces": relation(
        {"power": "power", "speed": "shaft_speed", "diameter": "diameter", "pressure_angle": "normal_pressure_angle", "helix_angle": "helix_angle"},
        {"torque": "moment", "Ft": "force", "Fr": "radial_load", "Fa": "axial_load", "Fy": "force", "Fz": "force"},
        "T=P/(2*pi*n/60); Ft=2*T/d; Fr=Ft*tan(alpha_n)/cos(beta); Fa=abs(Ft*tan(beta)); Fy=-Fr; Fz=-Ft",
        ["bearing-shaft"], "Single external helical gear, explicit analyzed shaft speed. x along shaft; external Fy=-Fr, Fz=-Ft."),
    "axial_force_couple": relation(
        {"axial_load": "axial_load", "diameter": "diameter", "direction": "direction"},
        {"My": "moment", "Mz": "moment"}, "r cross F: My=0; Mz=sign*Fa*d/2",
        ["support_equilibrium_derivation"], "Contact offset is in y plane; record coordinate convention; unknown direction requires both signs.", {"direction": ["positive", "negative"]}),
    "shaft_reactions_two_supports": relation(
        {"span": "span", "position": "position", "Fy": "force", "Fz": "force", "My": "moment", "Mz": "moment"},
        {"RAy": "force", "RBy": "force", "RAz": "force", "RBz": "force", "FrA": "radial_load", "FrB": "radial_load"},
        "RBy=-(a*Fy+Mz)/L; RBz=(-a*Fz+My)/L; RA=-F-RB; Fr=hypot(Ry,Rz)",
        ["support_equilibrium_derivation"], "One applied transverse load, 0<=a<=L; all two-plane loads and free couples required."),
    "resolve_axial_loads": relation(
        {"axial_load": "axial_load", "locating_end": "locating_end"}, {"FaA": "axial_load", "FaB": "axial_load"},
        "Locating end carries all external axial load; floating end carries zero", ["bearing-shaft"],
        "Explicit locating/floating evidence. No induced-thrust formulas for other bearing types.", {"locating_end": ["A", "B"]}),
    "lookup_coefficients": relation(
        {"axial_load": "axial_load", "static_capacity": "static_capacity", "table": "coefficient_table"},
        {"e": "coefficient", "X": "coefficient", "Y": "coefficient", "index": "ratio", "interpolation": "report"},
        "x=Fa/C0; interpolate table with its exact index and registered endpoint policy", ["S1", "S3"],
        "Ordinary single-row deep-groove ball; question table takes precedence. No f0 substitution or upper extrapolation."),
    "equivalent_dynamic_load": relation(
        {"radial_load": "radial_load", "axial_load": "axial_load", "rotation_factor": "rotation_factor", "e": "coefficient", "X": "coefficient", "Y": "coefficient", "load_factor": "load_factor"},
        {"P": "equivalent_dynamic_load", "branch": "label"}, "P=fp*(V*Fr if Fa<=e*V*Fr else X*V*Fr+Y*Fa)",
        ["S1", "S2"], "Load factor applied once; capacities are not applied loads."),
    "bearing_life_hours": relation(
        {"dynamic_capacity": "dynamic_capacity", "equivalent_load": "equivalent_dynamic_load", "speed": "shaft_speed"},
        {"L10h": "life_hours"}, "L10h=1e6/(60*n)*(C/P)^3", ["S2", "bearing-shaft"], "Ball bearings; C,P,n>0; 90 percent reliability."),
    "reliability_life": relation(
        {"basic_life": "life_hours", "factor": "reliability_factor"}, {"LRh": "life_hours"},
        "LRh=a1*L10h", ["S5"], "0<a1<=1, explicit source/table version; no unprovided aISO."),
    "equivalent_static_load": relation(
        {"radial_load": "radial_load", "axial_load": "axial_load", "static_capacity": "static_capacity"},
        {"P0": "equivalent_static_load", "s0": "safety_factor"}, "P0=max(Fr,.6*Fr+.5*Fa); s0=C0/P0",
        ["S4", "S6"], "Ordinary deep-groove ball; actual load; no invented acceptance threshold."),
    "required_dynamic_rating": relation(
        {"target_hours": "target_hours", "equivalent_load": "equivalent_dynamic_load", "speed": "shaft_speed", "factor": "reliability_factor"},
        {"C_required": "dynamic_capacity"}, "Cmin=P*(H*60*n/(a1*1e6))^(1/3)", ["S2", "S5"],
        "Capacity requirement only; no catalog selection."),
    "check_equilibrium": relation(
        {"span": "span", "position": "position", "Fy": "force", "Fz": "force", "My": "moment", "Mz": "moment", "RAy": "force", "RBy": "force", "RAz": "force", "RBz": "force"},
        {"residuals": "report"}, "Check both forces and moments against the independently bound load inventory",
        ["support_equilibrium_derivation"], "A zero residual does not by itself prove input completeness."),
    "geometry_position": relation(
        {"span": "span", "numeric_position": "position", "geometry": "geometry"}, {"position": "position"}, "a=L/2 or explicit numeric position", ["support_equilibrium_derivation"],
        "Conditional interpretation of explicit midpoint wording, kept separate from numeric dimensions.", {"geometry": ["midpoint", "numeric"]}),
    "transverse_components": relation(
        {"radial_load": "radial_load", "plane": "plane"}, {"Fy": "force", "Fz": "force", "My": "moment", "Mz": "moment"},
        "One centerline transverse load; choose coordinate plane; other transverse component and couples zero",
        ["support_equilibrium_derivation"], "Single pump/impeller transverse force acting on shaft centerline; no off-axis couple.", {"plane": ["y", "z"]}),
    "check_speed_limit": relation({"speed": "shaft_speed", "limit": "speed_limit"}, {"ratio": "ratio"},
        "speed / catalog_limit", ["bearing-shaft"], "Limit must come from the original question or an approved catalog row; ratio alone is not a whole-task judgment."),
}

# Only these dimension-preserving conversions are allowed at relation boundaries.
COMPATIBLE = {"radial_load": {"force"}, "force": {"radial_load"}}
