"""Measurement, estimation, supplier, inventory and procurement tools.

All quantities come from deterministic Python functions. Prices are only ever
read from stored quotations or supplied by the user — never invented.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models as m
from app.ai.tools_core import ToolContext, ToolRegistry, inr
from app.services import approvals, estimation, procurement
from app.services import inventory as inventory_svc
from app.services import measurements as M


class Empty(BaseModel):
    pass


class Opening(BaseModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    count: int = Field(1, ge=1)


class ConvertIn(BaseModel):
    value: float = Field(ge=0)
    from_unit: str
    to_unit: str


class RoomIn(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: str = "ft"
    openings: list[Opening] = []


class AreaIn(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    unit: str = "ft"
    count: int = Field(1, ge=1, description="Number of identical rooms")


class TileIn(BaseModel):
    area_sqft: float = Field(gt=0)
    tile_length: float = Field(gt=0)
    tile_width: float = Field(gt=0)
    tile_unit: str = "in"
    wastage_pct: float = Field(10, ge=0, le=50)
    tiles_per_box: Optional[int] = Field(None, ge=1)


class PaintIn(BaseModel):
    area_sqft: float = Field(gt=0)
    coats: int = Field(ge=1, le=6)
    coverage_sqft_per_litre: float = Field(
        gt=0, description="Required from the product datasheet; ask the user if unknown")
    wastage_pct: float = Field(5, ge=0, le=50)


class BrickIn(BaseModel):
    wall_area_sqft: float = Field(gt=0)
    wall_thickness_mm: float = Field(90, gt=0)
    wastage_pct: float = Field(5, ge=0, le=50)


class PlasterIn(BaseModel):
    area_sqft: float = Field(gt=0)
    thickness_mm: float = Field(12, gt=0)
    sand_ratio: float = Field(4, gt=0)


class AdhesiveIn(BaseModel):
    area_sqft: float = Field(gt=0)
    coverage_sqft_per_bag: float = Field(gt=0, description="From the adhesive datasheet")
    wastage_pct: float = Field(5, ge=0, le=50)


class WastageIn(BaseModel):
    quantity: float = Field(ge=0)
    wastage_pct: float = Field(10, ge=0, le=100)


class LabourCostIn(BaseModel):
    workers: int = Field(ge=1)
    days: float = Field(gt=0)
    rate: float = Field(ge=0, description="Agreed rate; never assume a market rate")
    hours_per_day: float = Field(8, gt=0)
    rate_type: str = "per_day"


class PriceIn(BaseModel):
    material_name: str


class CompareIn(BaseModel):
    material_name: str
    quantity: float = Field(gt=0)


class DeliveredIn(BaseModel):
    unit_price: float = Field(ge=0)
    quantity: float = Field(gt=0)
    tax_pct: float = Field(18, ge=0)
    delivery_charge: float = Field(0, ge=0)
    moq: float = Field(1, ge=0)


class PurchIn(BaseModel):
    required: float = Field(ge=0)
    buffer: float = Field(0, ge=0)
    usable_available: float = Field(0, ge=0)
    confirmed_incoming: float = Field(0, ge=0)


class SupplierSearchIn(BaseModel):
    query: str = ""
    category: Optional[str] = None


class POLine(BaseModel):
    material_name: str
    unit: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)


class POIn(BaseModel):
    items: list[POLine] = Field(min_length=1)
    supplier_id: Optional[int] = None
    expected_date: Optional[date] = None
    notes: str = ""


class MaterialIn(BaseModel):
    material_name: str


class StockDraftIn(BaseModel):
    material_name: str
    kind: str = Field(description="received | consumed | damaged | wasted | returned | adjust")
    quantity: float = Field(gt=0)
    note: str = ""


def latest_prices(db: Session, owner_id: int, material_name: str):
    """Most recent stored quotations for a material name (fuzzy match)."""
    return (db.query(m.MaterialPrice).join(m.Material)
            .filter(m.MaterialPrice.owner_id == owner_id,
                    m.Material.name.ilike(f"%{material_name}%"))
            .order_by(m.MaterialPrice.quotation_date.desc()).all())


def quotes_as_dicts(rows):
    return [{"unit_price": r.unit_price, "tax_pct": r.tax_pct, "delivery_charge": r.delivery_charge,
             "moq": r.moq, "valid_until": r.valid_until, "available": r.available,
             "source_type": r.source_type, "supplier": r.supplier.name if r.supplier else "Unspecified",
             "supplier_id": r.supplier_id,
             "lead_time_days": r.supplier.lead_time_days if r.supplier else None} for r in rows]


def register(reg: ToolRegistry) -> None:
    ctx: ToolContext = reg.ctx
    db = ctx.db
    user = ctx.user

    # ------------------------- measurements -------------------------
    def convert_units(value: float, from_unit: str, to_unit: str) -> dict:
        result = M.convert(value, from_unit, to_unit)
        return {"value": value, "from_unit": M.norm_unit(from_unit), "to_unit": M.norm_unit(to_unit),
                "result": round(result, 4), "formula": f"{value} {from_unit} × factor",
                "summary": f"{value} {from_unit} = {round(result, 4)} {to_unit}"}

    def floor_area(length: float, width: float, unit: str = "ft", count: int = 1) -> dict:
        L, W = M.to_feet(length, unit), M.to_feet(width, unit)
        area = L * W * count
        return {"floor_area_sqft": round(area, 3), "floor_area_sqm": round(area / M.SQFT_PER_SQM, 3),
                "formula": "length × width × count (converted to feet)",
                "assumptions": [f"Rectangular room measured in {unit}"],
                "summary": f"{round(area, 2)} sq ft floor area"}

    def ceiling_area(length: float, width: float, unit: str = "ft", count: int = 1) -> dict:
        out = floor_area(length, width, unit, count)
        out["ceiling_area_sqft"] = out.pop("floor_area_sqft")
        out["ceiling_area_sqm"] = out.pop("floor_area_sqm")
        out["summary"] = f"{out['ceiling_area_sqft']} sq ft ceiling area"
        return out

    def net_wall_area(length: float, width: float, height: float, unit: str = "ft",
                      openings: list[Opening] = ()) -> dict:  # type: ignore[assignment]
        g = M.room_geometry(length, width, height, unit,
                            [o.model_dump() if not isinstance(o, dict) else o for o in openings])
        return {**g, "summary": f"{g['net_wall_area_sqft']} sq ft net wall area"}

    # ------------------------- estimators -------------------------
    def tiles(area_sqft, tile_length, tile_width, tile_unit="in", wastage_pct=10, tiles_per_box=None):
        return estimation.tiles(area_sqft, tile_length, tile_width, tile_unit, wastage_pct, tiles_per_box)

    def paint(area_sqft, coats, coverage_sqft_per_litre, wastage_pct=5):
        return estimation.paint(area_sqft, coats, coverage_sqft_per_litre, wastage_pct)

    def primer(area_sqft, coats, coverage_sqft_per_litre, wastage_pct=5):
        return estimation.primer(area_sqft, coats, coverage_sqft_per_litre, wastage_pct)

    def bricks(wall_area_sqft, wall_thickness_mm=90, wastage_pct=5):
        return estimation.bricks(wall_area_sqft, wall_thickness_mm, wastage_pct=wastage_pct)

    def plaster(area_sqft, thickness_mm=12, sand_ratio=4):
        return estimation.plaster(area_sqft, thickness_mm, sand_ratio)

    def adhesive(area_sqft, coverage_sqft_per_bag, wastage_pct=5):
        return estimation.tile_adhesive(area_sqft, coverage_sqft_per_bag, wastage_pct)

    def wastage(quantity: float, wastage_pct: float) -> dict:
        final = M.apply_wastage(quantity, wastage_pct)
        return {"base_quantity": quantity, "wastage_pct": wastage_pct,
                "wastage_quantity": round(final - quantity, 4), "final_quantity": round(final, 4),
                "formula": "final = quantity × (1 + wastage% / 100)",
                "summary": f"{round(final, 2)} including {wastage_pct}% wastage"}

    def labour_cost(workers: int, days: float, rate: float, hours_per_day: float = 8,
                    rate_type: str = "per_day") -> dict:

        from app.services import labour
        total = labour.cost(workers, days, rate, hours_per_day, rate_type)
        return {"workers": workers, "days": days, "rate": rate, "rate_type": rate_type,
                "total_cost": float(total),
                "formula": ("rate × workers × days" if rate_type == "per_day"
                            else "rate × workers × days × hours" if rate_type == "per_hour"
                            else "rate × days"),
                "assumptions": ["Rate is the one you entered or approved"],
                "summary": f"Labour cost {inr(total)}"}

    # ------------------------- suppliers -------------------------
    def search_suppliers(query: str = "", category: Optional[str] = None) -> dict:
        q = db.query(m.Supplier).filter_by(owner_id=user.id)
        rows = q.all()
        rows = [s for s in rows if (s.name or "").strip()]
        if query:
            needle = query.lower()
            rows = [s for s in rows if needle in s.name.lower() or needle in (s.category or "").lower()
                    or needle in (s.location or "").lower()]
        if category:
            rows = [s for s in rows if (s.category or "").lower() == category.lower()]
        return {"count": len(rows), "suppliers": [
            {"id": s.id, "name": s.name, "email": s.email, "phone": s.phone, "location": s.location,
             "category": s.category, "lead_time_days": s.lead_time_days, "is_demo": s.is_demo}
            for s in rows[:20]],
            "summary": f"{len(rows)} supplier(s) found"}

    def lookup_price(material_name: str) -> dict:
        rows = latest_prices(db, user.id, material_name)
        if not rows:
            return {"found": False,
                    "message": ("No stored price for this material. Ask the user for a quotation, or add a "
                                "supplier quotation first. Do not estimate a market price."),
                    "summary": f"No stored price for '{material_name}'"}
        return {"found": True, "prices": [{
            "material": r.material.name, "unit": r.material.unit,
            "supplier": r.supplier.name if r.supplier else None,
            "unit_price": float(r.unit_price), "tax_pct": r.tax_pct,
            "delivery_charge": float(r.delivery_charge or 0), "moq": r.moq,
            "quotation_date": r.quotation_date.isoformat(),
            "valid_until": r.valid_until.isoformat() if r.valid_until else None,
            "source_type": r.source_type,
            "warning": ("SYNTHETIC demonstration price — not a market price"
                        if r.source_type == "demonstration" else ""),
        } for r in rows[:10]],
            "summary": f"{len(rows)} quotation(s) for '{material_name}'"}

    def compare(material_name: str, quantity: float) -> dict:
        rows = latest_prices(db, user.id, material_name)
        if not rows:
            return {"found": False, "message": "No stored quotations for this material.",
                    "summary": "No quotations to compare"}
        result = procurement.compare_quotes(quotes_as_dicts(rows), quantity)
        best = result[0]
        return {"found": True, "material": material_name, "quantity": quantity,
                "comparison": result[:10],
                "best": {"supplier": best["supplier"], "total": best["total"],
                         "expired": best["expired"]},
                "how_ranked": ("Expired quotations last, then unavailable, then total delivered cost "
                               "(unit price × buy quantity respecting MOQ + tax + delivery)."),
                "summary": f"Cheapest delivered option: {best['supplier']} at {inr(best['total'])}"}

    def quotation_validity(material_name: str) -> dict:
        rows = latest_prices(db, user.id, material_name)
        if not rows:
            return {"found": False, "summary": "No quotations stored"}
        today = date.today()
        soon = today + timedelta(days=14)
        out = []
        for r in rows:
            state = "no expiry recorded"
            if r.valid_until:
                state = ("expired" if r.valid_until < today
                         else "expiring soon" if r.valid_until <= soon else "valid")
            out.append({"supplier": r.supplier.name if r.supplier else None,
                        "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                        "state": state, "source_type": r.source_type})
        return {"materials": material_name, "quotations": out,
                "expired": sum(1 for o in out if o["state"] == "expired"),
                "summary": f"{sum(1 for o in out if o['state'] == 'expired')} expired quotation(s)"}

    def delivered_cost(unit_price: float, quantity: float, tax_pct: float = 18,
                       delivery_charge: float = 0, moq: float = 1) -> dict:
        c = procurement.delivered_cost(unit_price, tax_pct, delivery_charge, moq, quantity)
        return {**c, "formula": "unit price × max(quantity, MOQ) + tax + delivery",
                "summary": f"Delivered cost {inr(c['total'])}"}

    def purchase_requirement(required: float, buffer: float = 0, usable_available: float = 0,
                             confirmed_incoming: float = 0) -> dict:
        qty = procurement.purchase_requirement(required, buffer, usable_available, confirmed_incoming)
        return {"purchase_quantity": qty,
                "formula": "max(0, required + buffer − available − confirmed incoming)",
                "summary": f"Purchase {qty:g}"}

    def create_po(items: list[POLine], supplier_id: Optional[int] = None,
                  expected_date: Optional[date] = None, notes: str = "") -> dict:
        p = ctx.project()
        payload = {"items": [i.model_dump() for i in items], "supplier_id": supplier_id,
                   "expected_date": expected_date.isoformat() if expected_date else None,
                   "notes": notes}
        total = sum(i.quantity * i.unit_price for i in items)
        a = approvals.create(db, user, action="create_purchase_order", payload=payload,
                             project_id=p.id,
                             title=f"Draft purchase order for {p.name}",
                             summary=(f"{len(items)} line(s), estimated {inr(total)}. "
                                      f"Approval creates a DRAFT order only — nothing is ordered."),
                             conversation_id=ctx.conversation_id)
        return {"status": "approval_required", "approval_id": a.id, "estimated_total": round(total, 2),
                "message": f"Approval #{a.id} created. Approving creates a draft purchase order.",
                "summary": f"Purchase order approval #{a.id} created"}

    def delivery_status() -> dict:
        p = ctx.project()
        pos = db.query(m.PurchaseOrder).filter_by(project_id=p.id).all()
        if not pos:
            return {"found": False, "message": "No purchase orders for this project.",
                    "summary": "No purchase orders"}
        return {"orders": [procurement.serialize_po(po) for po in pos],
                "summary": f"{len(pos)} purchase order(s)"}

    # ------------------------- inventory -------------------------
    def site_inventory() -> dict:
        p = ctx.project()
        items = db.query(m.InventoryItem).filter_by(project_id=p.id).all()
        return {"project": p.name, "items": [{
            "material": i.material_name, "available": i.available, "unit": i.unit,
            "reserved": i.reserved, "incoming": i.incoming, "reorder_level": i.reorder_level,
            "location": i.location,
            "low": i.reorder_level > 0 and i.available <= i.reorder_level,
        } for i in items], "count": len(items),
            "summary": f"{len(items)} material(s) tracked"}

    def low_stock() -> dict:
        p = ctx.project()
        rows = [i for i in db.query(m.InventoryItem).filter_by(project_id=p.id)
                if i.reorder_level > 0 and i.available <= i.reorder_level]
        return {"low_stock": [{
            "material": i.material_name, "available": i.available, "unit": i.unit,
            "reorder_level": i.reorder_level,
            "recommended_reorder": inventory_svc.reorder_quantity(i),
        } for i in rows], "count": len(rows),
            "summary": f"{len(rows)} material(s) at or below reorder level"}

    def reorder_qty(material_name: str) -> dict:
        p = ctx.project()
        item = (db.query(m.InventoryItem)
                .filter(m.InventoryItem.project_id == p.id,
                        m.InventoryItem.material_name.ilike(f"%{material_name}%")).first())
        if not item:
            return {"found": False, "message": f"'{material_name}' is not tracked in this project's inventory.",
                    "summary": "Material not tracked"}
        qty = inventory_svc.reorder_quantity(item)
        return {"found": True, "material": item.material_name, "available": item.available,
                "unit": item.unit, "reorder_level": item.reorder_level, "reorder_quantity": qty,
                "rule": "Refill to 2× reorder level, minus available and incoming stock",
                "summary": f"Reorder {qty:g} {item.unit}"}

    def stock_draft(material_name: str, kind: str, quantity: float, note: str = "") -> dict:
        p = ctx.project()
        item = (db.query(m.InventoryItem)
                .filter(m.InventoryItem.project_id == p.id,
                        m.InventoryItem.material_name.ilike(f"%{material_name}%")).first())
        if not item:
            return {"status": "not_found",
                    "message": f"No inventory item named '{material_name}' in {p.name}.",
                    "summary": "Inventory item not found"}
        if kind not in inventory_svc.KINDS:
            return {"status": "invalid", "message": f"kind must be one of {sorted(inventory_svc.KINDS)}",
                    "summary": "Invalid transaction type"}
        if kind in inventory_svc.NEGATIVE and item.available - quantity < 0:
            return {"status": "invalid",
                    "message": f"Only {item.available:g} {item.unit} available; cannot remove {quantity:g}.",
                    "summary": "Insufficient stock"}
        a = approvals.create(db, user, action="stock_adjustment",
                             payload={"item_id": item.id, "kind": kind, "quantity": quantity,
                                      "note": note},
                             project_id=p.id,
                             title=f"{kind.title()} {quantity:g} {item.unit} of {item.material_name}",
                             summary=note or "Inventory change awaiting approval",
                             conversation_id=ctx.conversation_id)
        return {"status": "approval_required", "approval_id": a.id,
                "message": f"Approval #{a.id} created; stock has not changed yet.",
                "summary": f"Stock approval #{a.id} created"}

    def consumption(material_name: Optional[str] = None) -> dict:
        p = ctx.project()
        from app.services import analytics
        rows = analytics.material_consumption(db, user.id, p.id)
        if material_name:
            rows = [r for r in rows if material_name.lower() in r["material"].lower()]
        return {"project": p.name, "consumption": rows, "count": len(rows),
                "summary": f"{len(rows)} material(s) with recorded consumption"}

    reg.add("convert_measurement_units", "Convert length/area/volume/mass units.", ConvertIn,
            convert_units)
    reg.add("calculate_floor_area", "Floor area of one or more identical rectangular rooms.", AreaIn,
            floor_area)
    reg.add("calculate_ceiling_area", "Ceiling area of one or more identical rooms.", AreaIn,
            ceiling_area)
    reg.add("calculate_net_wall_area",
            "Floor, ceiling, gross and net wall area for a room with door/window openings.", RoomIn,
            net_wall_area)
    reg.add("estimate_tile_quantity", "Number of tiles for an area including wastage.", TileIn, tiles)
    reg.add("estimate_paint_quantity", "Paint litres; coverage must come from the datasheet.", PaintIn,
            paint)
    reg.add("estimate_primer_quantity", "Primer litres; coverage from the datasheet.", PaintIn, primer)
    reg.add("estimate_brick_quantity", "Bricks and mortar for NON-structural partition walls.", BrickIn,
            bricks)
    reg.add("estimate_plaster_materials", "Cement bags and sand for plastering.", PlasterIn, plaster)
    reg.add("estimate_tile_adhesive", "Tile adhesive bags for an area.", AdhesiveIn, adhesive)
    reg.add("calculate_wastage", "Apply a wastage percentage to a quantity.", WastageIn, wastage)
    reg.add("calculate_labour_cost", "Labour cost from workers × days × agreed rate.", LabourCostIn,
            labour_cost)
    reg.add("search_suppliers", "Search the supplier directory.", SupplierSearchIn, search_suppliers)
    reg.add("lookup_material_price", "Stored prices/quotations for a material (with source label).",
            PriceIn, lookup_price)
    reg.add("compare_supplier_prices", "Compare stored quotations by total delivered cost.", CompareIn,
            compare)
    reg.add("check_quotation_validity", "Check expiry state of stored quotations.", PriceIn,
            quotation_validity)
    reg.add("calculate_delivered_cost", "Unit price + tax + delivery respecting MOQ.", DeliveredIn,
            delivered_cost)
    reg.add("calculate_purchase_requirements",
            "max(0, required + buffer − available − incoming).", PurchIn, purchase_requirement)
    reg.add("get_delivery_status", "Purchase orders and delivery state for the project.", Empty,
            delivery_status, needs_project=True)
    reg.add("create_purchase_request", "Draft a purchase order (needs approval).", POIn, create_po,
            write=True, capability="supplier.write")
    reg.add("create_draft_purchase_order", "Draft a purchase order (needs approval).", POIn, create_po,
            write=True, capability="supplier.write")
    reg.add("get_site_inventory", "Inventory on site for the selected project.", Empty,
            site_inventory, needs_project=True)
    reg.add("check_low_stock", "Materials at or below reorder level.", Empty,
            low_stock, needs_project=True)
    reg.add("calculate_reorder_quantity", "Recommended reorder quantity for a material.", MaterialIn,
            reorder_qty)
    reg.add("create_stock_transaction_draft", "Propose a stock in/out/adjustment (needs approval).",
            StockDraftIn, stock_draft, write=True, capability="inventory.write")
    reg.add("get_material_consumption", "Material consumption from inventory transactions.",
            Empty, consumption)
