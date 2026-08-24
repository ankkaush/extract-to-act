"""Renders an InvoiceSpec to PDF bytes using reportlab. One flexible
builder rather than one function per layout family — the layout families
in invoice_specs.py (classic / two_column / minimalist / statement /
narrative / receipt) are expressed as conditional branches here, which
keeps 18 documents' worth of visual variation in one reviewable place
instead of scattered across near-duplicate functions.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from spike.formatting import format_amount, format_date
from spike.invoice_specs import InvoiceSpec

_STYLES = getSampleStyleSheet()


def _header_block(spec: InvoiceSpec) -> list:
    styles = _STYLES
    title_style = ParagraphStyle("InvoiceTitle", parent=styles["Title"], fontSize=18, spaceAfter=4)
    elements = []

    if spec.layout == "two_column":
        left = [
            Paragraph(f"<b>{spec.vendor_name}</b>", styles["Normal"]),
            Paragraph("123 Market Street", styles["Normal"]),
        ]
        due_text = f"Due: {format_date(spec.due_date, spec.date_style)}" if spec.due_date else ""
        right = [
            Paragraph(f"<b>Invoice #{spec.invoice_number}</b>", styles["Normal"]),
            Paragraph(f"Date: {format_date(spec.invoice_date, spec.date_style)}", styles["Normal"]),
            Paragraph(due_text, styles["Normal"]),
        ]
        header_table = Table([[left, right]], colWidths=[90 * mm, 90 * mm])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(header_table)
    else:
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Paragraph(f"<b>{spec.vendor_name}</b>", styles["Normal"]))
        elements.append(Paragraph(f"Invoice #: {spec.invoice_number}", styles["Normal"]))
        invoice_date_text = f"Invoice date: {format_date(spec.invoice_date, spec.date_style)}"
        elements.append(Paragraph(invoice_date_text, styles["Normal"]))
        if spec.due_date:
            due_date_text = f"Due date: {format_date(spec.due_date, spec.date_style)}"
            elements.append(Paragraph(due_date_text, styles["Normal"]))
        elif spec.payment_terms_text:
            elements.append(Paragraph(spec.payment_terms_text, styles["Normal"]))
        if spec.po_number:
            elements.append(Paragraph(f"PO Number: {spec.po_number}", styles["Normal"]))

    elements.append(Spacer(1, 10 * mm))
    return elements


# The receipt layout's 80mm page (64mm usable after margins) is
# narrower than the default column widths below assume — inv_18 first
# revealed this as a real rendering bug (totals rendered with their
# labels pushed off-page, only bare numbers visible) when the generated
# PDF was actually inspected, not just generated without error.
_RECEIPT_ITEM_COL_WIDTHS = [26 * mm, 8 * mm, 15 * mm, 15 * mm]
_RECEIPT_TOTALS_COL_WIDTHS = [34 * mm, 30 * mm]


def _line_items_table(spec: InvoiceSpec) -> Table:
    has_tax_column = any(li.tax_rate is not None for li in spec.line_items)
    header = ["Description", "Qty", "Unit Price", "Line Total"]
    if has_tax_column:
        header.insert(3, "Tax Rate")

    ambiguous = spec.ambiguous_currency_symbol
    rows = [header]
    for li in spec.line_items:
        row = [
            li.description,
            f"{li.quantity:g}",
            format_amount(li.unit_price, spec.currency, ambiguous_symbol_only=ambiguous),
            format_amount(li.line_total, spec.currency, ambiguous_symbol_only=ambiguous),
        ]
        if has_tax_column:
            row.insert(3, f"{li.tax_rate * 100:.0f}%" if li.tax_rate is not None else "-")
        rows.append(row)

    is_receipt = spec.layout == "receipt"
    col_widths = _RECEIPT_ITEM_COL_WIDTHS if is_receipt and not has_tax_column else None
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.92)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 6 if is_receipt else 9),
        ("TOPPADDING", (0, 0), (-1, -1), 2 if is_receipt else 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if is_receipt else 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 if is_receipt else 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 if is_receipt else 6),
    ]
    if is_receipt:
        style_commands.append(("WORDWRAP", (0, 0), (-1, -1), "CJK"))

    table = Table(rows, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle(style_commands))
    return table


def _totals_block(spec: InvoiceSpec) -> Table:
    def fmt(v: float) -> str:
        return format_amount(v, spec.currency, ambiguous_symbol_only=spec.ambiguous_currency_symbol)

    rows = []
    for label, value in spec.extra_total_lines:
        rows.append([label, fmt(value)])
    rows.append(["Subtotal", fmt(spec.subtotal)])
    if spec.tax or not spec.extra_total_lines:
        rows.append(["Tax", fmt(spec.tax)])
    total_label = "Total Due This Period" if spec.layout == "statement" else "Total"
    rows.append([total_label, fmt(spec.total)])
    if spec.layout == "statement":
        rows.append(["Amount Due", fmt(spec.total)])

    is_receipt = spec.layout == "receipt"
    col_widths = _RECEIPT_TOTALS_COL_WIDTHS if is_receipt else [60 * mm, 40 * mm]
    table = Table(rows, colWidths=col_widths, hAlign="RIGHT" if not is_receipt else "LEFT")
    style = [
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 7 if is_receipt else 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 2 if is_receipt else 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if is_receipt else 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]
    table.setStyle(TableStyle(style))
    return table


def render_invoice_pdf(spec: InvoiceSpec) -> bytes:
    buf = io.BytesIO()
    page_size = A4 if spec.layout == "receipt" else letter
    if spec.layout == "receipt":
        page_size = (80 * mm, 200 * mm)

    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=8 * mm if spec.layout == "receipt" else 20 * mm,
        rightMargin=8 * mm if spec.layout == "receipt" else 20 * mm,
        topMargin=8 * mm if spec.layout == "receipt" else 15 * mm,
        bottomMargin=8 * mm if spec.layout == "receipt" else 15 * mm,
    )

    story: list = []
    story.extend(_header_block(spec))

    if spec.narrative_text:
        story.append(Paragraph(spec.narrative_text, _STYLES["Normal"]))
    elif spec.lump_description:
        story.append(Paragraph(spec.lump_description, _STYLES["Normal"]))
        story.append(Spacer(1, 6 * mm))
        story.append(_totals_block(spec))
    elif spec.multi_page:
        midpoint = len(spec.line_items) // 2
        first_half = spec.line_items[:midpoint]
        second_half = spec.line_items[midpoint:]
        story.append(_line_items_table(_with_items(spec, first_half)))
        story.append(PageBreak())
        story.append(Paragraph(f"Invoice #{spec.invoice_number} (continued)", _STYLES["Normal"]))
        story.append(Spacer(1, 4 * mm))
        story.append(_line_items_table(_with_items(spec, second_half)))
        story.append(Spacer(1, 6 * mm))
        story.append(_totals_block(spec))
    else:
        story.append(_line_items_table(spec))
        story.append(Spacer(1, 6 * mm))
        story.append(_totals_block(spec))

    doc.build(story)
    return buf.getvalue()


def _with_items(spec: InvoiceSpec, items: list) -> InvoiceSpec:
    """Shallow copy with a different line_items list — used only to reuse
    _line_items_table() across the two halves of a multi-page invoice.
    """
    import dataclasses

    return dataclasses.replace(spec, line_items=items)
