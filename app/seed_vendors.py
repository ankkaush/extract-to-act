"""Seeds a small, realistic known-vendor table — see PLAN.md Phase 8.

Vendor names mirror the Phase 5 spike's synthetic invoice dataset (see
spike/invoice_specs.py) since that's already representative, real-shaped
test data — copied here as plain strings, not imported, since app code
never depends on the spike package (see spike/README.md, "why not part
of the application").

Not run automatically on app startup — a deliberate, deploy-time step,
same reasoning as running Alembic migrations manually rather than on
every boot.

Usage:
    python -m app.seed_vendors
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Vendor
from app.vendor_matching import normalize_vendor_name

SEED_VENDOR_NAMES = [
    "Bluepeak Office Supplies",
    "Nordfeld Mobelwerk GmbH",
    "Thistle & Co. Print Services Ltd",
    "Kestrel Consulting LLC",
    "Sakura Denki K.K.",
    "Harborline Industrial Supply",
    "Alpenweg Textilhandel AG",
    "Meridian Utilities Co.",
    "Coastal Freight Logistics",
    "Ridgeview Landscaping",
    "Northshore Print & Design",
    "Vestergaard Elektronik ApS",
    "Fernwood Legal Associates",
    "Granite Peak Construction Supply",
    "Ember & Oak Furniture Co.",
    "Sundara Textiles Pvt. Ltd.",
    "Juniper Creative Studio",
    "Corner Cafe Supply Co.",
]


def seed_vendors(session: Session) -> int:
    """Idempotent — inserts only names not already present by normalized
    form. Returns the number of new rows inserted.
    """
    existing = {row[0] for row in session.execute(select(Vendor.normalized_name)).all()}
    inserted = 0
    for name in SEED_VENDOR_NAMES:
        normalized = normalize_vendor_name(name)
        if normalized in existing:
            continue
        session.add(Vendor(name=name, normalized_name=normalized))
        existing.add(normalized)
        inserted += 1
    session.commit()
    return inserted


def main() -> None:
    session = SessionLocal()
    try:
        count = seed_vendors(session)
        skipped = len(SEED_VENDOR_NAMES) - count
        print(f"Seeded {count} new vendor(s) ({skipped} already present).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
