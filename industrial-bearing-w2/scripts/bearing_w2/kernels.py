"""Deterministic engineering functions, using canonical N, m, W, rpm, deg, h.

The caller validates types and provenance before invoking these functions.
No kernel makes a design choice, reads an answer, or contacts a model.
"""
from __future__ import annotations
import math
from .common import W2Error, finite

UNITS = {"N": ("force", 1), "kN": ("force", 1000), "m": ("length", 1),
         "mm": ("length", .001), "W": ("power", 1), "kW": ("power", 1000),
         "rpm": ("speed", 1), "r/min": ("speed", 1), "rev/min": ("speed", 1),
         "deg": ("angle", 1), "°": ("angle", 1), "rad": ("angle", 180 / math.pi),
         "h": ("time", 1), "hours": ("time", 1), "1": ("dimensionless", 1),
         "%": ("percent", 1), "N*m": ("moment", 1), "N*mm": ("moment", .001)}
CANONICAL = {"force": "N", "length": "m", "power": "W", "speed": "rpm",
             "angle": "deg", "time": "h", "dimensionless": "1", "percent": "%", "moment": "N*m"}


def normalize_quantities(value, unit):
    if unit not in UNITS:
        raise W2Error("E_UNIT", "unapproved unit", unit)
    dimension, scale = UNITS[unit]
    return {"value": finite(value) * scale, "unit": CANONICAL[dimension]}


def gear_forces(power, speed, diameter, pressure_angle, helix_angle):
    power, speed, diameter = finite(power, minimum=0), finite(speed, minimum=0, strict=True), finite(diameter, minimum=0, strict=True)
    if not 0 < pressure_angle < 90 or not -80 < helix_angle < 80:
        raise W2Error("E_RANGE", "invalid gear angles")
    torque = power / (2 * math.pi * speed / 60)
    ft = 2 * torque / diameter
    fr = ft * math.tan(math.radians(pressure_angle)) / math.cos(math.radians(helix_angle))
    fa = abs(ft * math.tan(math.radians(helix_angle)))
    return {"torque": torque, "Ft": ft, "Fr": fr, "Fa": fa,
            "Fy": -fr, "Fz": -ft}


def axial_force_couple(axial_load, diameter, direction):
    if direction not in ("positive", "negative"):
        raise W2Error("E_TYPE", "explicit couple direction required")
    return {"My": 0., "Mz": (1 if direction == "positive" else -1) *
            finite(axial_load, minimum=0) * finite(diameter, minimum=0, strict=True) / 2}


def shaft_reactions_two_supports(span, position, Fy, Fz, My, Mz):
    span = finite(span, minimum=0, strict=True)
    if not 0 <= position <= span:
        raise W2Error("E_RANGE", "single load must lie between supports")
    rby = -(position * Fy + Mz) / span
    rbz = (-position * Fz + My) / span
    ray, raz = -Fy - rby, -Fz - rbz
    return {"RAy": ray, "RBy": rby, "RAz": raz, "RBz": rbz,
            "FrA": math.hypot(ray, raz), "FrB": math.hypot(rby, rbz)}


def resolve_axial_loads(axial_load, locating_end):
    value = finite(axial_load, minimum=0)
    if locating_end not in ("A", "B"):
        raise W2Error("E_MISSING", "locating/floating evidence required")
    return {"FaA": value if locating_end == "A" else 0., "FaB": value if locating_end == "B" else 0.}


def lookup_coefficients(axial_load, static_capacity, table):
    index = finite(axial_load, minimum=0) / finite(static_capacity, minimum=0, strict=True)
    if table.get("index") != "Fa/C0":
        raise W2Error("E_TYPE", "Fa/C0 and f0Fa/C0 are not interchangeable")
    rows = table["rows"]
    if not 1 <= len(rows) <= 32 or any(rows[i]["x"] >= rows[i+1]["x"] for i in range(len(rows)-1)):
        raise W2Error("E_SOURCE", "invalid coefficient table")
    if axial_load == 0:
        return {"e": 0., "X": 1., "Y": 0., "index": 0., "interpolation": {"branch": "pure_radial_no_table_needed"}}
    if index < rows[0]["x"]:
        if table.get("lower_rule") != "clamp_first":
            raise W2Error("E_RANGE", "below approved table domain")
        lo = hi = rows[0]
    elif index > rows[-1]["x"]:
        raise W2Error("E_RANGE", "extrapolation not approved")
    else:
        lo = max((r for r in rows if r["x"] <= index), key=lambda r: r["x"])
        hi = min((r for r in rows if r["x"] >= index), key=lambda r: r["x"])
    weight = 0 if lo["x"] == hi["x"] else (index - lo["x"]) / (hi["x"] - lo["x"])
    result = {key: lo[key] + weight * (hi[key] - lo[key]) for key in ("e", "X", "Y")}
    return {**result, "index": index, "interpolation": {"lower": lo["x"], "upper": hi["x"], "fraction": weight}}


def equivalent_dynamic_load(radial_load, axial_load, rotation_factor, e, X, Y, load_factor):
    fr, fa = finite(radial_load, minimum=0), finite(axial_load, minimum=0)
    if rotation_factor not in (1., 1.2):
        raise W2Error("E_TYPE", "unsupported rotation condition")
    for name, value in (("e", e), ("X", X), ("Y", Y), ("load_factor", load_factor)):
        finite(value, name, minimum=0, strict=name in ("X", "load_factor"))
    low = fa <= e * rotation_factor * fr
    p = rotation_factor * fr if low else X * rotation_factor * fr + Y * fa
    return {"P": load_factor * p, "branch": "radial" if low else "combined"}


def bearing_life_hours(dynamic_capacity, equivalent_load, speed):
    c = finite(dynamic_capacity, minimum=0, strict=True)
    p = finite(equivalent_load, minimum=0, strict=True)
    n = finite(speed, minimum=0, strict=True)
    return {"L10h": 1e6 / (60 * n) * (c / p) ** 3}


def reliability_life(basic_life, factor):
    if not 0 < factor <= 1:
        raise W2Error("E_RANGE", "a1 must be in (0,1]")
    return {"LRh": finite(basic_life, minimum=0) * factor}


def equivalent_static_load(radial_load, axial_load, static_capacity):
    p0 = max(finite(radial_load, minimum=0), .6 * radial_load + .5 * finite(axial_load, minimum=0))
    if p0 <= 0:
        raise W2Error("E_RANGE", "zero load has no finite static safety ratio")
    return {"P0": p0, "s0": finite(static_capacity, minimum=0, strict=True) / p0}


def required_dynamic_rating(target_hours, equivalent_load, speed, factor):
    if not 0 < factor <= 1:
        raise W2Error("E_RANGE", "invalid reliability factor")
    h = finite(target_hours, minimum=0, strict=True)
    n = finite(speed, minimum=0, strict=True)
    return {"C_required": finite(equivalent_load, minimum=0, strict=True) * (h * 60 * n / (factor * 1e6)) ** (1/3)}


def check_equilibrium(span, position, Fy, Fz, My, Mz, RAy, RBy, RAz, RBz):
    residuals = {"force_y": RAy + RBy + Fy, "force_z": RAz + RBz + Fz,
                 "moment_z": span * RBy + position * Fy + Mz,
                 "moment_y": -span * RBz - position * Fz + My}
    if max(abs(v) for v in residuals.values()) > 1e-7 * max(1, abs(Fy), abs(Fz), abs(My), abs(Mz)):
        raise W2Error("E_INVARIANT", "two-plane equilibrium failed")
    return {"residuals": residuals}


def geometry_position(span, numeric_position, geometry):
    if geometry not in ("midpoint", "numeric"):
        raise W2Error("E_TYPE", "unregistered geometry")
    finite(span, minimum=0, strict=True)
    if not 0 <= numeric_position <= span:
        raise W2Error("E_RANGE", "numeric position outside span")
    return {"position": span / 2 if geometry == "midpoint" else numeric_position}


def transverse_components(radial_load, plane):
    load = finite(radial_load, minimum=0)
    if plane not in ("y", "z"):
        raise W2Error("E_TYPE", "coordinate plane required")
    return {"Fy": -load if plane == "y" else 0., "Fz": -load if plane == "z" else 0., "My": 0., "Mz": 0.}


def check_speed_limit(speed, limit):
    finite(speed, minimum=0, strict=True)
    finite(limit, minimum=0, strict=True)
    return {"ratio": speed / limit}


FUNCTIONS = {f.__name__: f for f in (gear_forces, axial_force_couple, shaft_reactions_two_supports,
             resolve_axial_loads, lookup_coefficients, equivalent_dynamic_load, bearing_life_hours,
             reliability_life, equivalent_static_load, required_dynamic_rating, check_equilibrium,
             geometry_position, transverse_components, check_speed_limit)}
