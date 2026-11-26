"""Reproducible SYNTHETIC demo data (fixed seed).

Every price is tagged source_type='demonstration'. Each project scenario has a
consistent BOQ, task list, expenses and inventory for its project type, so the
Interior Painting demo never shows tile lines or masonry tasks.

Creates demo@buildbudget.dev / DemoPass123 (change it!).
Run: uv run python scripts/seed_demo_data.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.core.security import hash_password
from app.database import SessionLocal, init_db

random.seed(42)

CATS = {
    "Cement": ("bag", 380), "Bricks": ("pcs", 8), "Concrete blocks": ("pcs", 38),
    "Sand": ("cum", 1800), "Aggregates": ("cum", 1500), "Tiles": ("sqft", 55),
    "Tile adhesive": ("bag", 600), "Grout": ("kg", 90), "Paint": ("litre", 380),
    "Primer": ("litre", 260), "Putty": ("kg", 38), "Plumbing pipes": ("m", 140),
    "Plumbing fittings": ("pcs", 120), "Electrical wire": ("m", 38),
    "Electrical fittings": ("pcs", 90), "Doors": ("pcs", 6500), "Windows": ("pcs", 7500),
    "Waterproofing": ("litre", 330), "Hardware": ("pcs", 60), "Flooring": ("sqft", 85),
}
BRANDS = ["Alpha", "Beta", "Gamma", "Delta", "Omega"]
SUPPLIERS = [
    "Demo Build Mart", "Sample Cement Depot", "Synthetic Tiles Co", "Example Hardware",
    "Demo Paints Hub", "Mock Sand & Aggregates", "Test Electricals", "Sample Plumbing House",
    "Demo Doors & Windows", "Fictional Waterproofing", "Sample Bricks Works",
    "Demo Flooring Studio", "Example Builders Supply", "Mock Site Needs", "Synthetic Trade Centre",
]

# name, project_type, approved budget, spend fraction, BOQ lines, tasks, inventory
# BOQ line: (category, description, unit, qty, unit_rate, tax_pct, labour_cost)
# task: (name, duration_days, start_offset_days, progress, depends_on_indexes)
SCENARIOS = [
    {
        "name": "Demo: 12x15 ft Room, Nashik", "type": "single_room", "budget": 200000, "spend": 0.92,
        "boq": [
            ("Flooring", "Vitrified floor tiles 600x600 mm (demo rate)", "pcs", 50, 720, 18, 0),
            ("Flooring", "Tile adhesive and grout (demo rate)", "bag", 8, 600, 18, 0),
            ("Painting", "Interior emulsion, 2 coats (demo rate)", "litre", 12, 380, 18, 0),
            ("Painting", "Primer and putty (demo rate)", "litre", 10, 260, 18, 0),
            ("Finishing", "Skilled labour — tiling and painting (demo rate)", "day", 8, 900, 0, 0),
        ],
        "tasks": [
            ("Site preparation and measurement", 3, -20, 60, []),
            ("Floor tiling", 5, -12, 45, [0]),
            ("Wall painting", 4, -5, 20, [1]),
            ("Snag fixing and handover", 2, 8, 0, [2]),
        ],
        "inventory": [("Cement (demo)", "bag", 5, 10), ("Tile adhesive (demo)", "bag", 3, 6),
                      ("Grout (demo)", "kg", 12, 10)],
        "expenses": [("Materials", 0.62), ("Labour", 0.28), ("Transportation", 0.10)],
    },
    {
        "name": "Demo: Bathroom Renovation", "type": "bathroom_renovation", "budget": 120000, "spend": 0.5,
        "boq": [
            ("Waterproofing", "Wet-area waterproofing membrane (demo rate)", "litre", 20, 330, 18, 0),
            ("Flooring", "Anti-skid floor tiles (demo rate)", "sqft", 60, 85, 18, 0),
            ("Finishing", "Wall tiles (demo rate)", "sqft", 120, 55, 18, 0),
            ("Plumbing", "Concealed plumbing pipes and fittings (demo rate)", "set", 1, 18000, 18, 0),
            ("Sanitaryware", "WC, basin and shower fittings (demo rate)", "set", 1, 26000, 18, 0),
            ("Finishing", "Plumber and tiler labour (demo rate)", "day", 10, 950, 0, 0),
        ],
        "tasks": [
            ("Demolition of old finishes", 2, -14, 100, []),
            ("Waterproofing", 2, -10, 100, [0]),
            ("Plumbing rough-in", 3, -7, 70, [1]),
            ("Tiling", 4, -2, 30, [2]),
            ("Sanitaryware and fixtures", 2, 4, 0, [3]),
        ],
        "inventory": [("Waterproofing membrane (demo)", "litre", 4, 8),
                      ("Floor tiles (demo)", "sqft", 18, 20), ("Cement (demo)", "bag", 6, 10)],
        "expenses": [("Materials", 0.55), ("Labour", 0.30), ("Transportation", 0.15)],
    },
    {
        "name": "Demo: Kitchen Renovation", "type": "kitchen_renovation", "budget": 250000, "spend": 0.78,
        "boq": [
            ("Cabinetry", "Modular base and wall cabinets (demo rate)", "set", 1, 85000, 18, 0),
            ("Countertop", "Quartz countertop (demo rate)", "sqft", 28, 450, 18, 0),
            ("Finishing", "Kitchen wall tiles (demo rate)", "sqft", 90, 55, 18, 0),
            ("Plumbing", "Sink and mixer with plumbing (demo rate)", "set", 1, 12500, 18, 0),
            ("Electrical", "Kitchen wiring and appliance points (demo rate)", "point", 10, 900, 18, 0),
            ("Finishing", "Carpenter and electrician labour (demo rate)", "day", 9, 1000, 0, 0),
        ],
        "tasks": [
            ("Remove old kitchen", 3, -18, 100, []),
            ("Electrical and plumbing points", 4, -12, 100, [0]),
            ("Cabinet installation", 5, -6, 45, [1]),
            ("Countertop and sink", 3, 0, 20, [2]),
            ("Wall tiling and final finish", 4, 5, 0, [2]),
        ],
        "inventory": [("Wall tiles (demo)", "sqft", 15, 24), ("Electrical wire (demo)", "m", 40, 50),
                      ("Plumbing fittings (demo)", "pcs", 4, 10)],
        "expenses": [("Materials", 0.60), ("Labour", 0.25), ("Transportation", 0.15)],
    },
    {
        "name": "Demo: Boundary Wall", "type": "boundary_wall", "budget": 300000, "spend": 0.2,
        "boq": [
            ("Masonry", "Bricks for non-structural infill (demo rate)", "pcs", 9000, 8, 18, 0),
            ("Masonry", "Cement for mortar (demo rate)", "bag", 90, 380, 18, 0),
            ("Masonry", "Sand for mortar (demo rate)", "cum", 12, 1800, 18, 0),
            ("Finishing", "Plaster to both faces (demo rate)", "sqft", 1500, 32, 18, 0),
            ("Fabrication", "MS gate with primer and paint (demo rate)", "pcs", 1, 42000, 18, 0),
            ("Masonry", "Mason and helper labour (demo rate)", "day", 20, 900, 0, 0),
        ],
        "tasks": [
            ("Excavation for wall footing", 3, -9, 55, []),
            ("Footing and plinth (engineer-approved)", 5, -5, 20, [0]),
            ("Brickwork above plinth", 8, 2, 0, [1]),
            ("Plastering", 4, 12, 0, [2]),
            ("Gate installation", 2, 18, 0, [2]),
        ],
        "inventory": [("Cement (demo)", "bag", 8, 20), ("Bricks (demo)", "pcs", 600, 1000),
                      ("Sand (demo)", "cum", 1, 2)],
        "expenses": [("Materials", 0.65), ("Labour", 0.25), ("Transportation", 0.10)],
    },
    {
        "name": "Demo: Interior Painting", "type": "painting", "budget": 60000, "spend": 1.05,
        "boq": [
            ("Painting", "Interior emulsion, 2 coats (demo rate)", "litre", 30, 380, 18, 0),
            ("Painting", "Primer (demo rate)", "litre", 16, 260, 18, 0),
            ("Painting", "Wall putty (demo rate)", "kg", 80, 38, 18, 0),
            ("Painting", "Painter labour (demo rate)", "day", 8, 700, 0, 0),
            ("Painting", "Surface masking and sanding consumables (demo rate)", "set", 1, 1500, 18, 0),
        ],
        "tasks": [
            ("Furniture covering and surface preparation", 2, -8, 100, []),
            ("Putty and sanding", 3, -5, 80, [0]),
            ("Primer coat", 2, -1, 40, [1]),
            ("Two finish coats", 4, 2, 0, [2]),
            ("Touch-up and handover", 1, 6, 0, [3]),
        ],
        "inventory": [("Paint (demo)", "litre", 5, 12), ("Primer (demo)", "litre", 3, 8),
                      ("Putty (demo)", "kg", 25, 20)],
        "expenses": [("Materials", 0.48), ("Labour", 0.42), ("Transportation", 0.10)],
    },
]


def seed_projects(db, u):
    """Create the five type-consistent demonstration projects for `u`."""
    for sc in SCENARIOS:
        p = m.Project(owner_id=u.id, name=sc["name"], project_type=sc["type"], location="Nashik",
                      latitude=19.9975, longitude=73.7898, budget=sc["budget"], status="active",
                      is_demo=True, description="SYNTHETIC demonstration project")
        db.add(p)
        db.flush()
        for no, (cat, desc, unit, qty, rate, tax, labour) in enumerate(sc["boq"], 1):
            material = qty * rate + labour
            db.add(m.BOQItem(project_id=p.id, item_no=no, category=cat, description=desc, unit=unit,
                             quantity=qty, unit_rate=rate, material_cost=qty * rate, labour_cost=labour,
                             total=round(material * (1 + tax / 100), 2), tax_pct=tax,
                             rate_source="demonstration",
                             assumptions="Synthetic demonstration quantity and rate — replace with a real quotation."))
        spent = sc["budget"] * sc["spend"]
        for k, (cat, share) in enumerate(sc["expenses"]):
            db.add(m.Expense(project_id=p.id, category=cat, amount=round(spent * share, 2),
                             description=f"Demo {cat.lower()} expense for {sc['type'].replace('_', ' ')}",
                             vendor="Demo Vendor", invoice_no=f"DEMO-{p.id}-{k + 1}",
                             expense_date=date.today() - timedelta(days=20 * k)))
        for name, unit, available, reorder in sc["inventory"]:
            db.add(m.InventoryItem(project_id=p.id, material_name=name, unit=unit, available=available,
                                   reorder_level=reorder))
        task_ids = []
        for name, duration, offset, progress, deps in sc["tasks"]:
            t = m.Task(project_id=p.id, name=name, duration_days=duration,
                       start_date=date.today() + timedelta(days=offset), progress=progress)
            db.add(t)
            db.flush()
            for dep in deps:
                db.add(m.TaskDep(task_id=t.id, depends_on_id=task_ids[dep]))
            task_ids.append(t.id)
    db.commit()


def main():
    init_db()
    db = SessionLocal()
    if db.query(m.User).filter_by(email="demo@buildbudget.dev").first():
        print("Demo data already present.")
        return
    u = m.User(email="demo@buildbudget.dev", name="Demo User", password_hash=hash_password("DemoPass123"),
               role="homeowner")
    db.add(u)
    db.flush()
    sups = [m.Supplier(owner_id=u.id, name=n, email=f"sales{i}@example.invalid", location="Demo City",
                       lead_time_days=random.randint(1, 7), reliability=round(random.uniform(0.6, 0.98), 2),
                       is_demo=True) for i, n in enumerate(SUPPLIERS)]
    db.add_all(sups)
    db.flush()
    mats = []
    for cat, (unit, base) in CATS.items():
        for v in range(5):
            mt = m.Material(name=f"{cat} - {BRANDS[v]} grade {v + 1}", category=cat, unit=unit,
                            specification="synthetic demo item")
            mats.append((mt, base))
            db.add(mt)
    db.flush()
    for mt, base in mats:
        for s in random.sample(sups, 3):
            db.add(m.MaterialPrice(owner_id=u.id, material_id=mt.id, supplier_id=s.id,
                                   unit_price=round(base * random.uniform(0.85, 1.2), 2), tax_pct=18,
                                   delivery_charge=random.choice([0, 300, 500, 800]),
                                   moq=random.choice([1, 5, 10]),
                                   quotation_date=date.today() - timedelta(days=random.randint(0, 40)),
                                   valid_until=date.today() + timedelta(days=random.randint(-10, 60)),
                                   source_type="demonstration"))
    for cat, rate in (("Masonry", 900), ("Painting", 700), ("Plastering", 800), ("Flooring", 850),
                      ("Plumbing", 1000), ("Electrical", 1000)):
        db.add(m.LabourRate(owner_id=u.id, category=cat, rate_type="per_day", rate=rate,
                            source_type="demonstration"))

    seed_projects(db, u)
    db.commit()
    print(f"Seeded: {len(CATS)} categories, {len(mats)} materials, {len(sups)} suppliers, "
          f"{db.query(m.MaterialPrice).count()} price quotations, {len(SCENARIOS)} projects. ALL SYNTHETIC.")
    print("Login: demo@buildbudget.dev / DemoPass123")


if __name__ == "__main__":
    main()
