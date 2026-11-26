"""Non-structural material quantity estimators (deterministic).

Structural items (foundations, reinforcement, beams, columns, slabs, load-bearing walls)
are deliberately NOT estimated here: they require engineer-approved quantities.
"""
from __future__ import annotations

import math

from . import measurements as M

REF = "Rule-of-thumb formula implemented in code; verify against the project-approved specification / datasheet."
STRUCTURAL_NOTICE = ("Preliminary estimate only. Not a structural design. Foundations, reinforcement, "
                     "beams, columns, slabs and load-bearing walls need engineer-approved quantities.")
BAG_CEMENT_M3 = 0.0347       # volume of one 50 kg cement bag (common assumption)
DRY_VOLUME_FACTOR = 1.33     # wet-to-dry mortar volume factor (common assumption)


def _ceil(x: float) -> int:
    return math.ceil(round(x, 6))


def _result(item, unit, base, wastage, final, formula, inputs, assumptions, secondary=None):
    return {"item": item, "unit": unit, "base_quantity": round(base, 3), "wastage_pct": wastage,
            "final_quantity": final, "formula": formula, "inputs": inputs,
            "assumptions": assumptions, "secondary": secondary or {},
            "source_reference": REF, "notice": STRUCTURAL_NOTICE}


def tiles(area_sqft, tile_length, tile_width, tile_unit="in", wastage_pct=10.0, tiles_per_box=None):
    A = M.require_positive("area_sqft", area_sqft)
    tl, tw = M.to_feet(tile_length, tile_unit), M.to_feet(tile_width, tile_unit)
    tile_area = tl * tw
    raw = A / tile_area
    final = _ceil(M.apply_wastage(raw, wastage_pct))
    sec = {}
    if tiles_per_box:
        sec["boxes"] = _ceil(final / M.require_positive("tiles_per_box", tiles_per_box))
    return _result("Tiles", "pcs", raw, wastage_pct, final,
                   "tiles = ceil(area / tile_area * (1 + wastage%))",
                   {"area_sqft": A, "tile_area_sqft": round(tile_area, 4)},
                   [f"Wastage {wastage_pct}% (cuts/breakage); user-adjustable"], sec)


def paint(area_sqft, coats, coverage_sqft_per_litre, wastage_pct=5.0):
    """Coverage MUST come from the product datasheet - it is a required input, never defaulted."""
    A = M.require_positive("area_sqft", area_sqft)
    n = int(M.require_positive("coats", coats))
    cov = M.require_positive("coverage_sqft_per_litre", coverage_sqft_per_litre)
    base = A * n / cov
    final = round(M.apply_wastage(base, wastage_pct), 2)
    return _result("Paint", "litre", base, wastage_pct, final,
                   "litres = area * coats / coverage * (1 + wastage%)",
                   {"area_sqft": A, "coats": n, "coverage_sqft_per_litre": cov},
                   ["Coverage rate supplied by user/datasheet", "Surface preparation not included"])


def primer(area_sqft, coats, coverage_sqft_per_litre, wastage_pct=5.0):
    r = paint(area_sqft, coats, coverage_sqft_per_litre, wastage_pct)
    r["item"] = "Primer"
    return r


def bricks(wall_area_sqft, wall_thickness_mm=90, brick_l_mm=190, brick_w_mm=90, brick_h_mm=90,
           mortar_mm=10, wastage_pct=5.0, mortar_ratio_sand=6):
    A_m2 = M.require_positive("wall_area_sqft", wall_area_sqft) / M.SQFT_PER_SQM
    t = M.require_positive("wall_thickness_mm", wall_thickness_mm)
    bl, bw, bh, mortar = (x / 1000 for x in (brick_l_mm, brick_w_mm, brick_h_mm, mortar_mm))
    wythes = max(1, round(t / brick_w_mm))
    raw = A_m2 * wythes / ((bl + mortar) * (bh + mortar))
    final = _ceil(M.apply_wastage(raw, wastage_pct))
    wall_vol = A_m2 * (t / 1000)
    mortar_wet = max(0.0, wall_vol - raw * bl * bw * bh)
    dry = mortar_wet * DRY_VOLUME_FACTOR
    r = mortar_ratio_sand
    cement_bags = _ceil((dry / (1 + r)) / BAG_CEMENT_M3)
    sand_m3 = round(dry * r / (1 + r), 3)
    return _result("Bricks (non-load-bearing partition only)", "pcs", raw, wastage_pct, final,
                   "bricks = area_m2 * wythes / ((l+mortar)*(h+mortar)) * (1 + wastage%)",
                   {"wall_area_m2": round(A_m2, 3), "wythes": wythes, "brick_mm": [brick_l_mm, brick_w_mm, brick_h_mm],
                    "mortar_mm": mortar_mm},
                   ["Applies to non-structural partition walls only",
                    f"Mortar mix 1:{r}; wet->dry factor {DRY_VOLUME_FACTOR}; cement bag {BAG_CEMENT_M3} m3",
                    "Secondary quantities (cement, sand) are indicative"],
                   {"mortar_cement_bags": cement_bags, "mortar_sand_m3": sand_m3})


def plaster(area_sqft, thickness_mm=12, sand_ratio=4, wastage_pct=5.0):
    A_m2 = M.require_positive("area_sqft", area_sqft) / M.SQFT_PER_SQM
    t = M.require_positive("thickness_mm", thickness_mm)
    wet = A_m2 * t / 1000
    dry = M.apply_wastage(wet * DRY_VOLUME_FACTOR, wastage_pct)
    bags = _ceil((dry / (1 + sand_ratio)) / BAG_CEMENT_M3)
    sand = round(dry * sand_ratio / (1 + sand_ratio), 3)
    return _result("Plaster (cement + sand)", "bags cement", dry, wastage_pct, bags,
                   "dry = area_m2 * t * 1.33 * (1+wastage%); cement=dry/(1+r)/0.0347",
                   {"area_m2": round(A_m2, 3), "thickness_mm": t, "mix": f"1:{sand_ratio}"},
                   [f"Dry volume factor {DRY_VOLUME_FACTOR}", "Indicative; confirm mix with site engineer"],
                   {"sand_m3": sand, "dry_mortar_m3": round(dry, 4)})


def tile_adhesive(area_sqft, coverage_sqft_per_bag, wastage_pct=5.0):
    A = M.require_positive("area_sqft", area_sqft)
    cov = M.require_positive("coverage_sqft_per_bag", coverage_sqft_per_bag)
    base = A / cov
    return _result("Tile adhesive", "bags", base, wastage_pct, _ceil(M.apply_wastage(base, wastage_pct)),
                   "bags = ceil(area / coverage_per_bag * (1+wastage%))",
                   {"area_sqft": A, "coverage_sqft_per_bag": cov}, ["Coverage from datasheet (user-supplied)"])


KINDS = {"tiles": tiles, "paint": paint, "primer": primer, "bricks": bricks,
         "plaster": plaster, "tile_adhesive": tile_adhesive}


def run(kind: str, params: dict) -> dict:
    if kind not in KINDS:
        raise ValueError(f"Unknown estimate kind '{kind}'. Supported: {sorted(KINDS)}")
    try:
        return KINDS[kind](**params)
    except TypeError as e:
        raise ValueError(f"Invalid parameters for '{kind}': {e}") from e
