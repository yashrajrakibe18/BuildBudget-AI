"""Deterministic unit conversion and geometry. All inputs validated; no LLM involved."""
from __future__ import annotations

_ALIASES = {
    "ft": "ft", "feet": "ft", "foot": "ft", "in": "in", "inch": "in", "inches": "in",
    "m": "m", "metre": "m", "meter": "m", "metres": "m", "cm": "cm", "mm": "mm",
    "sqft": "sqft", "sq ft": "sqft", "ft2": "sqft", "sqm": "sqm", "sq m": "sqm", "m2": "sqm",
    "cft": "cft", "cuft": "cft", "ft3": "cft", "cum": "cum", "m3": "cum",
    "l": "l", "litre": "l", "liter": "l", "litres": "l",
    "kg": "kg", "tonne": "tonne", "t": "tonne",
}
# factor to base unit within each dimension
_DIM = {
    "length": ({"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "in": 0.0254}),
    "area": ({"sqm": 1.0, "sqft": 0.09290304}),
    "volume": ({"cum": 1.0, "cft": 0.028316846592, "l": 0.001}),
    "mass": ({"kg": 1.0, "tonne": 1000.0}),
}
SQFT_PER_SQM = 1 / 0.09290304


def norm_unit(u: str) -> str:
    key = u.strip().lower().replace(".", "")
    if key not in _ALIASES:
        raise ValueError(f"Unsupported unit '{u}'")
    return _ALIASES[key]


def _dim_of(u: str) -> str:
    for d, table in _DIM.items():
        if u in table:
            return d
    raise ValueError(f"Unit '{u}' has no convertible dimension")


def require_positive(name: str, v: float, allow_zero: bool = False) -> float:
    if v is None or (v < 0) or (v == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'>= 0' if allow_zero else '> 0'} (got {v})")
    return float(v)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    require_positive("value", value, allow_zero=True)
    a, b = norm_unit(from_unit), norm_unit(to_unit)
    if _dim_of(a) != _dim_of(b):
        raise ValueError(f"Cannot convert {a} ({_dim_of(a)}) to {b} ({_dim_of(b)})")
    t = _DIM[_dim_of(a)]
    return value * t[a] / t[b]


def to_feet(value: float, unit: str) -> float:
    return convert(value, unit, "ft")


def rect_area(length: float, width: float) -> float:
    return require_positive("length", length) * require_positive("width", width)


def room_geometry(length: float, width: float, height: float, unit: str = "ft",
                  openings: list[dict] | None = None) -> dict:
    """Return areas in sq ft and sq m. openings: [{width,height,count}] in same unit."""
    L, W, H = (to_feet(require_positive(n, v), unit) for n, v in
               (("length", length), ("width", width), ("height", height)))
    floor = L * W
    gross_wall = 2 * (L + W) * H
    open_area = 0.0
    for o in openings or []:
        ow, oh = to_feet(require_positive("opening width", o["width"]), unit), \
                 to_feet(require_positive("opening height", o["height"]), unit)
        open_area += ow * oh * int(o.get("count", 1))
    if open_area >= gross_wall:
        raise ValueError("Openings exceed gross wall area")
    net = gross_wall - open_area

    def r(x: float) -> float:
        return round(x, 3)

    return {
        "floor_area_sqft": r(floor), "ceiling_area_sqft": r(floor),
        "gross_wall_area_sqft": r(gross_wall), "openings_area_sqft": r(open_area),
        "net_wall_area_sqft": r(net), "floor_area_sqm": r(floor / SQFT_PER_SQM),
        "net_wall_area_sqm": r(net / SQFT_PER_SQM),
        "formula": "floor=L*W; gross wall=2*(L+W)*H; net wall=gross-sum(openings)",
        "inputs": {"length_ft": r(L), "width_ft": r(W), "height_ft": r(H)},
    }


def apply_wastage(quantity: float, wastage_pct: float) -> float:
    require_positive("quantity", quantity, allow_zero=True)
    require_positive("wastage_pct", wastage_pct, allow_zero=True)
    return quantity * (1 + wastage_pct / 100.0)
