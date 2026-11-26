"""Reset ONLY synthetic demonstration projects, then optionally reseed them.

Real projects, the demo user account and the shared supplier/material/price
catalog are never deleted. Requires an explicit --confirm flag.

    uv run python scripts/reset_demo_data.py --confirm
    uv run python scripts/reset_demo_data.py --confirm --no-reseed
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seed_demo_data import seed_projects  # same directory; scenario data lives with the seed script

from app import models as m
from app.database import SessionLocal, init_db
from app.services.demo_reset import delete_demo_projects, demo_project_ids

DEMO_EMAIL = "demo@buildbudget.dev"


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete and optionally reseed synthetic demo projects only.")
    parser.add_argument("--confirm", action="store_true",
                        help="Required. Acknowledges that demonstration records will be deleted.")
    parser.add_argument("--no-reseed", action="store_true",
                        help="Delete demo projects without recreating the demo scenarios.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        pids = demo_project_ids(db)
        if not pids:
            print("No demonstration projects found. Nothing to reset.")
            return 0
        names = [row[0] for row in db.query(m.Project.name).filter(m.Project.id.in_(pids)).all()]
        print(f"{len(pids)} demonstration project(s) matched:")
        for name in names:
            print(f"  - {name}")
        print("Real projects, the demo account and shared catalog data are not touched.")
        if not args.confirm:
            print("\nRefusing to delete anything without --confirm.")
            return 2

        counts = delete_demo_projects(db)
        print(f"Deleted {counts['projects']} demonstration project(s) and their child records.")

        if args.no_reseed:
            print("Skipped reseeding (--no-reseed).")
            return 0
        user = db.query(m.User).filter_by(email=DEMO_EMAIL).first()
        if not user:
            print(f"Cannot reseed: {DEMO_EMAIL} does not exist. Run scripts/seed_demo_data.py first.")
            return 1
        seed_projects(db, user)
        print(f"Reseeded {len(pids)} consistent demonstration project(s) for {DEMO_EMAIL}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
