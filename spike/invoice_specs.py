"""The 18-document synthetic evaluation set — approved dataset design, see
PLAN.md Phase 5 and docs/extraction-strategy.md.

This is the single source of truth: each spec's `fields`/`line_items` is
the *authoritative* ground truth, written first. spike/generate_samples.py
renders a document FROM this data — never the other way around — so
there is no transcription step and therefore no transcription risk. This
is a meaningful methodological advantage over grading against real
invoices, where ground truth has to be read off the document by a human
after the fact.

Every spec's `notes` field states exactly what that document is designed
to stress, so a provider's failure on it is diagnostic, not just a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LineItemSpec:
    description: str
    quantity: float
    unit_price: float
    line_total: float
    tax_rate: float | None = None  # only rendered/relevant for inv_03


@dataclass
class InvoiceSpec:
    doc_id: str
    notes: str
    difficulty: str  # easy | medium | hard
    layout: str
    currency: str
    date_style: str  # us | eu_dot | dd_mm_yyyy_slash | dd_mm_yyyy_dash | iso
    vendor_name: str
    invoice_number: str
    invoice_date: str  # ISO, ground truth
    due_date: str | None  # ISO, ground truth — None is a valid, tested answer (inv_13)
    subtotal: float
    tax: float
    total: float
    line_items: list[LineItemSpec] = field(default_factory=list)
    narrative_text: str | None = None  # inv_17: total is stated in prose, not a table
    lump_description: str | None = None  # inv_04: single line description, no table
    extra_total_lines: list[tuple[str, float]] = field(default_factory=list)  # inv_08 distractors
    payment_terms_text: str | None = None  # inv_13: "Net 30" instead of a due date
    po_number: str | None = None  # inv_12 — rendered for realism, not a scored field (see evaluate.py)
    ambiguous_currency_symbol: bool = False  # inv_11: render bare "$", ground truth is still CAD
    degrade: str | None = None  # None | "stamp_scan" (inv_09) | "low_quality_scan" (inv_10)
    rotate_page_degrees: int = 0  # inv_15: rotate the finished PDF page, text layer intact
    multi_page: bool = False  # inv_14

    def ground_truth_json(self) -> dict:
        return {
            "fields": {
                "vendor_name": self.vendor_name,
                "invoice_number": self.invoice_number,
                "invoice_date": self.invoice_date,
                "due_date": self.due_date,
                "currency": self.currency,
                "subtotal": self.subtotal,
                "tax": self.tax,
                "total": self.total,
            },
            "line_items": [
                {
                    "description": li.description,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "line_total": li.line_total,
                }
                for li in self.line_items
            ],
        }


INVOICE_SPECS: list[InvoiceSpec] = [
    InvoiceSpec(
        doc_id="inv_01_baseline_usd",
        notes="Baseline — clean, standard layout. Should be easy for every provider; a floor, not a stress test.",
        difficulty="easy",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Bluepeak Office Supplies",
        invoice_number="INV-10234",
        invoice_date="2026-02-03",
        due_date="2026-03-05",
        subtotal=777.50,
        tax=62.20,
        total=839.70,
        line_items=[
            LineItemSpec("Copy Paper (Case)", 10, 34.50, 345.00),
            LineItemSpec("Toner Cartridge - Black", 4, 89.00, 356.00),
            LineItemSpec("Desk Organizer", 6, 12.75, 76.50),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_02_eu_locale",
        notes="EUR currency, EU date (DD.MM.YYYY) and number grouping (1.234,56). Tests locale-format parsing.",
        difficulty="easy",
        layout="classic",
        currency="EUR",
        date_style="eu_dot",
        vendor_name="Nordfeld Mobelwerk GmbH",
        invoice_number="RE-2026-0042",
        invoice_date="2026-01-15",
        due_date="2026-02-14",
        subtotal=514.50,
        tax=97.76,
        total=612.26,
        line_items=[
            LineItemSpec("Buerostuhl Modell X", 2, 189.00, 378.00),
            LineItemSpec("Schreibtischlampe", 3, 45.50, 136.50),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_03_two_column_mixed_tax",
        notes="Two-column letterhead layout, GBP, mixed per-line tax rates (0% zero-rated + 20% standard).",
        difficulty="easy",
        layout="two_column",
        currency="GBP",
        date_style="us",
        vendor_name="Thistle & Co. Print Services Ltd",
        invoice_number="TC-88231",
        invoice_date="2026-03-01",
        due_date="2026-03-31",
        subtotal=360.00,
        tax=48.00,
        total=408.00,
        line_items=[
            LineItemSpec("Business Cards (500)", 1, 45.00, 45.00, tax_rate=0.20),
            LineItemSpec("Books - Printed Catalogue", 1, 120.00, 120.00, tax_rate=0.0),
            LineItemSpec("Banner Printing", 2, 60.00, 120.00, tax_rate=0.20),
            LineItemSpec("Design Consultation", 1, 75.00, 75.00, tax_rate=0.20),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_04_no_line_items",
        notes="No line-item table at all — a single lump total with a text description. Tests whether the "
        "provider forces a table structure that isn't there, or correctly returns an empty line_items list.",
        difficulty="medium",
        layout="minimalist",
        currency="USD",
        date_style="us",
        vendor_name="Kestrel Consulting LLC",
        invoice_number="KC-0099",
        invoice_date="2026-02-20",
        due_date="2026-03-20",
        subtotal=4500.00,
        tax=0.00,
        total=4500.00,
        lump_description="Strategic advisory services - February 2026",
    ),
    InvoiceSpec(
        doc_id="inv_05_jpy_no_decimals",
        notes="JPY has no decimal subunit. Tests whether a provider wrongly assumes 2-decimal formatting.",
        difficulty="medium",
        layout="classic",
        currency="JPY",
        date_style="iso",
        vendor_name="Sakura Denki K.K.",
        invoice_number="SD-20260212",
        invoice_date="2026-02-12",
        due_date="2026-03-12",
        subtotal=47500,
        tax=4750,
        total=52250,
        line_items=[
            LineItemSpec("USB-C Hub", 5, 3200, 16000),
            LineItemSpec("Wireless Mouse", 10, 1800, 18000),
            LineItemSpec("Laptop Stand", 3, 4500, 13500),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_06_dense_table",
        notes="12 line items in one dense table. Tests line-item extraction robustness at volume.",
        difficulty="medium",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Harborline Industrial Supply",
        invoice_number="HIS-55214",
        invoice_date="2026-01-28",
        due_date="2026-02-27",
        subtotal=565.93,
        tax=45.27,
        total=611.20,
        line_items=[
            LineItemSpec("Hex Bolt M6x40 (box)", 1, 12.00, 12.00),
            LineItemSpec("Washer Set", 2, 8.50, 17.00),
            LineItemSpec("Cable Tie (100ct)", 5, 3.20, 16.00),
            LineItemSpec("Junction Box", 1, 45.00, 45.00),
            LineItemSpec("Conduit Fitting", 3, 22.75, 68.25),
            LineItemSpec("Wire Nut", 10, 1.10, 11.00),
            LineItemSpec("Mounting Bracket", 4, 6.60, 26.40),
            LineItemSpec("Safety Glasses", 2, 19.99, 39.98),
            LineItemSpec("Power Drill", 1, 150.00, 150.00),
            LineItemSpec("Drill Bit Set", 6, 4.25, 25.50),
            LineItemSpec("Extension Cord", 2, 33.00, 66.00),
            LineItemSpec("Tool Bag", 1, 88.80, 88.80),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_07_discount_subtotal",
        notes="Per-line discounts shown alongside a pre-discount and post-discount subtotal. Ground truth "
        "'subtotal' is the post-discount figure tax is actually computed on — tests whether the provider "
        "picks the right one.",
        difficulty="medium",
        layout="classic",
        currency="EUR",
        date_style="eu_dot",
        vendor_name="Alpenweg Textilhandel AG",
        invoice_number="AW-3390",
        invoice_date="2026-02-10",
        due_date="2026-03-10",
        subtotal=2128.00,
        tax=404.32,
        total=2532.32,
        line_items=[
            LineItemSpec("T-Shirts (Bulk, 10% discount applied)", 100, 8.00, 720.00),
            LineItemSpec("Hoodies (10% discount applied)", 50, 22.00, 990.00),
            LineItemSpec("Caps (5% discount applied)", 80, 5.50, 418.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_08_ambiguous_total_labels",
        notes="Statement-style layout with several similarly-labeled dollar amounts (Previous Balance, "
        "Payments Received, Balance Forward, Total Due This Period, Amount Due). Ground truth 'total' is "
        "$340.00 — tests semantic disambiguation, not just finding *a* number near the word 'total'.",
        difficulty="hard",
        layout="statement",
        currency="USD",
        date_style="us",
        vendor_name="Meridian Utilities Co.",
        invoice_number="MU-778812",
        invoice_date="2026-02-01",
        due_date="2026-02-28",
        subtotal=340.00,
        tax=0.00,
        total=340.00,
        line_items=[LineItemSpec("Electricity usage - Feb 2026", 1, 340.00, 340.00)],
        extra_total_lines=[
            ("Previous Balance", 120.00),
            ("Payments Received", -120.00),
            ("Balance Forward", 0.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_09_stamped_scan",
        notes="Rendered as an image with no text layer (forces real OCR), slightly rotated, with a red "
        "'PAID' stamp overlapping the totals area. Tests OCR quality plus whether a stray annotation "
        "confuses field extraction.",
        difficulty="hard",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Coastal Freight Logistics",
        invoice_number="CFL-40221",
        invoice_date="2026-01-20",
        due_date="2026-02-19",
        subtotal=2425.00,
        tax=0.00,
        total=2425.00,
        line_items=[
            LineItemSpec("Freight - Container 40ft", 1, 2200.00, 2200.00),
            LineItemSpec("Fuel Surcharge", 1, 150.00, 150.00),
            LineItemSpec("Handling Fee", 1, 75.00, 75.00),
        ],
        degrade="stamp_scan",
    ),
    InvoiceSpec(
        doc_id="inv_10_low_quality_scan",
        notes="Image-only, rotated ~5deg, blurred, low contrast, mild noise. A pure OCR-quality stress "
        "test isolated from semantic ambiguity — every field here is otherwise unambiguous.",
        difficulty="hard",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Ridgeview Landscaping",
        invoice_number="RL-9081",
        invoice_date="2026-02-15",
        due_date="2026-03-17",
        subtotal=540.00,
        tax=43.20,
        total=583.20,
        line_items=[
            LineItemSpec("Lawn Care - Monthly", 1, 150.00, 150.00),
            LineItemSpec("Mulch Installation", 2, 85.00, 170.00),
            LineItemSpec("Tree Trimming", 1, 220.00, 220.00),
        ],
        degrade="low_quality_scan",
    ),
    InvoiceSpec(
        doc_id="inv_11_ambiguous_currency",
        notes="Vendor address is in Toronto, ON but every amount is shown with a bare '$' (no CAD/ISO "
        "code). Ground truth currency is CAD. Tests a real production risk: a bare currency symbol is "
        "genuinely ambiguous, and a provider defaulting to USD here would be a realistic, costly mistake.",
        difficulty="hard",
        layout="classic",
        currency="CAD",
        date_style="us",
        vendor_name="Northshore Print & Design (Toronto, ON)",
        invoice_number="NPD-6620",
        invoice_date="2026-02-05",
        due_date="2026-03-07",
        subtotal=625.00,
        tax=81.25,
        total=706.25,
        line_items=[
            LineItemSpec("Brochure Printing", 500, 0.85, 425.00),
            LineItemSpec("Design Fee", 1, 200.00, 200.00),
        ],
        ambiguous_currency_symbol=True,
    ),
    InvoiceSpec(
        doc_id="inv_12_po_number",
        notes="Includes a prominent PO number field, EUR, DD/MM/YYYY. PO number itself isn't a scored "
        "field yet (not in the app's promoted schema — see docs/data-model.md) but its presence is "
        "realistic and worth having in the set for Phase 8+ matching work later.",
        difficulty="medium",
        layout="classic",
        currency="EUR",
        date_style="dd_mm_yyyy_slash",
        vendor_name="Vestergaard Elektronik ApS",
        invoice_number="VE-2231",
        invoice_date="2026-01-30",
        due_date="2026-03-01",
        subtotal=525.00,
        tax=99.75,
        total=624.75,
        po_number="PO-55810",
        line_items=[
            LineItemSpec("Router Model R200", 4, 65.00, 260.00),
            LineItemSpec("Network Switch 8-port", 2, 110.00, 220.00),
            LineItemSpec("Cable Management Kit", 3, 15.00, 45.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_13_no_due_date",
        notes="No explicit due date — only 'Payment Terms: Net 30' text. Ground truth due_date is null. "
        "Tests whether a provider correctly returns null rather than computing/hallucinating a date.",
        difficulty="medium",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Fernwood Legal Associates",
        invoice_number="FLA-1188",
        invoice_date="2026-02-01",
        due_date=None,
        subtotal=1050.00,
        tax=0.00,
        total=1050.00,
        payment_terms_text="Payment Terms: Net 30",
        line_items=[
            LineItemSpec("Legal Consultation - 3hrs", 3, 250.00, 750.00),
            LineItemSpec("Document Review", 1, 300.00, 300.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_14_multi_page",
        notes="Two-page invoice, line items split across both pages, totals on page 2. Tests multi-page "
        "handling.",
        difficulty="hard",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Granite Peak Construction Supply",
        invoice_number="GPCS-33410",
        invoice_date="2026-01-10",
        due_date="2026-02-09",
        subtotal=4695.00,
        tax=375.60,
        total=5070.60,
        multi_page=True,
        line_items=[
            LineItemSpec("Lumber 2x4x8", 200, 4.25, 850.00),
            LineItemSpec("Plywood Sheet", 50, 28.00, 1400.00),
            LineItemSpec("Concrete Mix (80lb)", 60, 6.75, 405.00),
            LineItemSpec("Rebar #4", 100, 3.10, 310.00),
            LineItemSpec("Roofing Shingles (bundle)", 40, 32.00, 1280.00),
            LineItemSpec("Safety Equipment Set", 10, 45.00, 450.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_15_rotated_digital",
        notes="Normal clean digital text layer (fully extractable), but the PDF page itself is rotated "
        "90 degrees via page metadata — a realistic phone-scanned-PDF-with-wrong-orientation case. Tests "
        "orientation handling even when OCR isn't strictly required.",
        difficulty="medium",
        layout="classic",
        currency="USD",
        date_style="us",
        vendor_name="Ember & Oak Furniture Co.",
        invoice_number="EO-7754",
        invoice_date="2026-02-18",
        due_date="2026-03-20",
        subtotal=1359.00,
        tax=108.72,
        total=1467.72,
        rotate_page_degrees=90,
        line_items=[
            LineItemSpec("Oak Dining Table", 1, 899.00, 899.00),
            LineItemSpec("Dining Chair (set of 4)", 1, 460.00, 460.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_16_inr_lakh_format",
        notes="INR with Indian lakh-style number grouping (Rs 2,00,000.00) and DD-MM-YYYY dates. Tests "
        "non-Western number grouping, which a naive comma-grouping assumption gets wrong.",
        difficulty="medium",
        layout="classic",
        currency="INR",
        date_style="dd_mm_yyyy_dash",
        vendor_name="Sundara Textiles Pvt. Ltd.",
        invoice_number="ST/2026/0341",
        invoice_date="2026-02-08",
        due_date="2026-03-10",
        subtotal=200000.00,
        tax=36000.00,
        total=236000.00,
        line_items=[
            LineItemSpec("Cotton Fabric (per meter)", 2000, 45.00, 90000.00),
            LineItemSpec("Silk Fabric (per meter)", 500, 220.00, 110000.00),
        ],
    ),
    InvoiceSpec(
        doc_id="inv_17_narrative_no_table",
        notes="No table at all — the charge is stated in a prose paragraph. The genuinely "
        "AI-favoring case this project's own docs call out: semantic extraction from "
        "unstructured text, not table parsing.",
        difficulty="hard",
        layout="narrative",
        currency="USD",
        date_style="us",
        vendor_name="Juniper Creative Studio",
        invoice_number="JCS-2026-014",
        invoice_date="2026-02-25",
        due_date="2026-03-25",
        subtotal=3750.00,
        tax=0.00,
        total=3750.00,
        narrative_text=(
            "For branding and creative direction services rendered throughout February 2026, "
            "including logo refinement, brand guideline development, and two rounds of stakeholder "
            "revisions, the amount payable is $3,750.00."
        ),
    ),
    InvoiceSpec(
        doc_id="inv_18_receipt_compact",
        notes="Compact receipt/thermal-printer-style layout on a narrow page. Tests "
        "small/non-standard page dimensions and tight spacing.",
        difficulty="medium",
        layout="receipt",
        currency="USD",
        date_style="us",
        vendor_name="Corner Cafe Supply Co.",
        invoice_number="CCS-4471",
        invoice_date="2026-02-22",
        due_date="2026-03-01",
        subtotal=328.00,
        tax=26.24,
        total=354.24,
        line_items=[
            LineItemSpec("Coffee Beans (5lb bag)", 4, 38.00, 152.00),
            LineItemSpec("Paper Cups (1000ct)", 2, 45.00, 90.00),
            LineItemSpec("Napkins (case)", 3, 18.00, 54.00),
            LineItemSpec("Cleaning Supplies Kit", 1, 32.00, 32.00),
        ],
    ),
]

_doc_ids = [s.doc_id for s in INVOICE_SPECS]
assert len(set(_doc_ids)) == len(_doc_ids), "duplicate doc_id in INVOICE_SPECS"
assert 15 <= len(INVOICE_SPECS) <= 20, "dataset size must stay within the approved 15-20 range"
