"""Professional PDF (ReportLab) and Excel (OpenPyXL) reports.

Design rules:
* the rupee glyph is not in the built-in PDF fonts, so PDFs print "Rs." while
  Excel uses the real ₹ number format;
* every report carries the preliminary-estimate disclaimer, data sources and a
  scope note;
* tables repeat their header row and wrap text so nothing is clipped.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table as XLTable
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings

NAVY = "#142139"
AMBER = "#F59E0B"
GREY = "#64748B"
LIGHT = "#F5F7FA"

DISCLAIMER = (
    "Preliminary planning and cost-estimation report. It is not a substitute for a qualified "
    "civil/structural engineer, and it is not a structural design or certification. Structural "
    "elements (foundations, reinforcement, beams, columns, slabs, load-bearing walls) require "
    "engineer-approved quantities. Prices tagged 'demonstration' are synthetic sample data, not "
    "market prices."
)

BOQ_COLS = ["item_no", "category", "description", "unit", "quantity", "unit_rate", "material_cost",
            "labour_cost", "tax_pct", "total", "rate_source", "approval_status", "assumptions"]
BOQ_HEADERS = ["#", "Category", "Description", "Unit", "Qty", "Rate", "Material", "Labour",
               "Tax %", "Total", "Rate source", "Status", "Assumptions"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def money(v) -> str:
    try:
        return f"Rs. {float(v):,.2f}"
    except (TypeError, ValueError):
        return "Rs. 0.00"


def _num(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def boq_rows(items) -> list[list]:
    rows = []
    for i in items:
        rows.append([i.item_no, i.category, i.description, i.unit, f"{i.quantity:g}",
                     _num(i.unit_rate), _num(i.material_cost), _num(i.labour_cost),
                     f"{i.tax_pct:g}", _num(i.total), i.rate_source, i.approval_status,
                     (i.assumptions or "")[:220]])
    return rows


def boq_csv(items) -> bytes:
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(BOQ_COLS)
    for row in boq_rows(items):
        w.writerow(row)
    return b.getvalue().encode()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
class _NumberedDoc(SimpleDocTemplate):
    def __init__(self, path, title: str, subtitle: str, **kw):
        super().__init__(path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                         topMargin=30 * mm, bottomMargin=20 * mm, **kw)
        self.report_title = title
        self.report_subtitle = subtitle

    def afterFlowable(self, flowable):  # pragma: no cover - layout hook
        pass

    def build(self, flowables, onFirstPage=None, onLaterPages=None):
        def decorate(canvas, doc):
            canvas.saveState()
            w, h = A4
            canvas.setFillColor(colors.HexColor(NAVY))
            canvas.rect(0, h - 22 * mm, w, 22 * mm, stroke=0, fill=1)
            canvas.setFillColor(colors.HexColor(AMBER))
            canvas.rect(0, h - 24 * mm, w, 2 * mm, stroke=0, fill=1)
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 15)
            canvas.drawString(16 * mm, h - 13 * mm, "BuildBudget AI")
            canvas.setFont("Helvetica", 8.5)
            canvas.drawRightString(w - 16 * mm, h - 12 * mm, self.report_title)
            canvas.drawRightString(w - 16 * mm, h - 16 * mm, self.report_subtitle)
            canvas.setFillColor(colors.HexColor(GREY))
            canvas.setFont("Helvetica", 7.5)
            canvas.drawString(16 * mm, 12 * mm,
                              "Preliminary estimate — verify with a qualified engineer. "
                              "Demonstration prices are synthetic.")
            canvas.drawRightString(w - 16 * mm, 12 * mm, f"Page {doc.page}")
            canvas.restoreState()

        return super().build(flowables, onFirstPage=decorate, onLaterPages=decorate)


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Title"], fontSize=17, textColor=colors.HexColor(NAVY),
                             spaceAfter=2, alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5,
                             textColor=colors.HexColor(NAVY), spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=8.6, leading=11.5),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontSize=7.2, leading=9),
        "muted": ParagraphStyle("muted", parent=base["BodyText"], fontSize=7.6, leading=9.5,
                                textColor=colors.HexColor(GREY)),
    }


def _kpi_table(kpis: list[tuple[str, str]]):
    if not kpis:
        return None
    cells = [[Paragraph(f"<b>{label}</b>", _styles()["small"]),
              Paragraph(str(value), _styles()["small"])] for label, value in kpis]
    cols = 2
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    flat = []
    for row in rows:
        if len(row) < cols:
            row.append([Paragraph("", _styles()["small"]), Paragraph("", _styles()["small"])])
        flat.append([c for pair in row for c in pair])
    t = Table(flat, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _data_table(header: list[str], rows: list[list], widths: list[float] | None = None,
                font_size: float = 7.0):
    st = _styles()["small"]
    data = [[Paragraph(f"<b>{h}</b>", st) for h in header]]
    for r in rows:
        data.append([Paragraph("" if c is None else str(c), ParagraphStyle(
            "cell", parent=st, fontSize=font_size, leading=font_size + 1.6)) for c in r])
    t = Table(data, repeatRows=1, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def pdf_report(title: str, subtitle: str, *, project_info: list[tuple[str, str]] | None = None,
               kpis: list[tuple[str, str]] | None = None,
               sections: list[dict] | None = None,
               sources: list[str] | None = None,
               assumptions: list[str] | None = None,
               limitations: list[str] | None = None) -> bytes:
    """Build a branded, paginated PDF. Sections: {heading, paragraphs, bullets, table}."""
    st = _styles()
    buf = io.BytesIO()
    doc = _NumberedDoc(buf, title, subtitle)
    els: list = [Paragraph(title, st["h1"]), Paragraph(subtitle, st["body"]),
                 Paragraph(f"Report date: {date.today():%d %B %Y} · {settings.app_name} "
                           f"v{settings.version}", st["muted"]), Spacer(1, 5), Spacer(1, 3)]
    if project_info:
        els.append(_kpi_table(project_info))
        els.append(Spacer(1, 4))
    if kpis:
        els.append(_kpi_table(kpis))
        els.append(Spacer(1, 4))
    for sec in sections or []:
        block = [Paragraph(sec["heading"], st["h2"])]
        for p in sec.get("paragraphs", []) or []:
            block.append(Paragraph(p, st["body"]))
            block.append(Spacer(1, 2))
        for b in sec.get("bullets", []) or []:
            block.append(Paragraph(f"• {b}", st["body"]))
        if sec.get("table"):
            t = sec["table"]
            block.append(Spacer(1, 3))
            block.append(_data_table(t["header"], t["rows"], t.get("widths"), t.get("font_size", 7)))
        if sec.get("page_break"):
            block.append(PageBreak())
        # Keep a heading with its first paragraph; let long tables split across pages
        # (they repeat their header row).
        if len(block) <= 2 and not sec.get("page_break"):
            els.append(KeepTogether(block))
        else:
            els.extend(block)
    if sources:
        els += [Paragraph("Data sources", st["h2"])]
        els += [Paragraph(f"• {s}", st["body"]) for s in sources]
    if assumptions:
        els += [Paragraph("Assumptions", st["h2"])]
        els += [Paragraph(f"• {a}", st["body"]) for a in assumptions]
    if limitations:
        els += [Paragraph("Scope & limitations", st["h2"])]
        els += [Paragraph(f"• {x}", st["body"]) for x in limitations]
    els += [Spacer(1, 8), Paragraph(DISCLAIMER, st["muted"])]
    doc.build(_flatten(els))
    return buf.getvalue()


def _flatten(items):
    out = []
    for item in items:
        if isinstance(item, list):
            out.extend(_flatten(item))
        elif item is not None:
            out.append(item)
    return out


def boq_pdf(project_name: str, items, budget_summary: dict | None = None) -> bytes:
    total = sum(float(i.total or 0) for i in items)
    kpis = [
        ("Listed items", str(len(items))),
        ("Estimated total (listed items)", money(total)),
    ]
    if budget_summary:
        kpis += [("Approved budget", money(budget_summary["approved_budget"])),
                 ("Actual expenses", money(budget_summary["actual_expenses"])),
                 ("Remaining budget", money(budget_summary["remaining_budget"])),
                 ("Budget utilisation",
                  f"{budget_summary['utilization_pct']}%" if budget_summary["utilization_pct"] is not None
                  else "No budget set")]
    return pdf_report(
        f"Bill of Quantities — {project_name}", "Preliminary estimate",
        kpis=kpis,
        sections=[{
            "heading": "Bill of quantities",
            "table": {"header": BOQ_HEADERS, "rows": boq_rows(items),
                      "widths": [8, 17, 52, 12, 14, 20, 20, 18, 12, 22, 22, 16, 55],
                      "font_size": 6.8},
        }, {
            "heading": "Scope note",
            "paragraphs": [
                "Items not listed (for example foundation, roof slab or structural reinforcement) are "
                "pending professional input and are NOT included in this total.",
            ],
        }],
        sources=["Quantities from the deterministic estimator and BOQ records in BuildBudget AI"],
        assumptions=["Rates are the ones you entered or the stored supplier quotation used for the item.",
                     "Wastage allowances are shown in each item's assumptions."],
        limitations=["Not a structural design.", "Tax treatment follows the rate recorded per item."],
    )


def budget_pdf(project, summary: dict, expenses, items) -> bytes:
    by_cat = summary.get("expenses_by_category", {})
    return pdf_report(
        f"Budget & expense report — {project.name}", "Financial position",
        project_info=[("Project", project.name), ("Status", project.status.title()),
                      ("Location", project.location or "—"),
                      ("Project manager", project.manager_name or "—")],
        kpis=[("Approved budget", money(summary["approved_budget"])),
              ("Estimated (BOQ revision %s)" % (summary.get("boq_revision") or "—"),
               money(summary["estimated_cost"])),
              ("Actual expenses", money(summary["actual_expenses"])),
              ("Remaining budget", money(summary["remaining_budget"])),
              ("Utilisation", f"{summary['utilization_pct']}%" if summary["utilization_pct"] is not None
               else "No budget set")],
        sections=[{
            "heading": "Expenses by category",
            "table": {"header": ["Category", "Amount"], "widths": [90, 60],
                      "rows": [[k, money(v)] for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]},
        }, {
            "heading": "Expense history",
            "table": {"header": ["Date", "Category", "Vendor", "Invoice", "Description", "Amount"],
                      "widths": [42, 50, 60, 40, 110, 55],
                      "rows": [[e.expense_date.strftime("%d-%b-%Y"), e.category, e.vendor or "—",
                                e.invoice_no or "—", (e.description or "")[:80], money(e.amount)]
                               for e in expenses]},
        }, {
            "heading": "BOQ items",
            "table": {"header": ["#", "Description", "Unit", "Qty", "Rate", "Total"],
                      "widths": [12, 120, 25, 25, 40, 45],
                      "rows": [[i.item_no, i.description, i.unit, f"{i.quantity:g}",
                                money(i.unit_rate), money(i.total)] for i in items]},
        }],
        sources=["Recorded expenses and the current BOQ revision"],
        limitations=["Committed but unrecorded costs are not included.",
                     "The BOQ estimate covers only entered items."],
    )


def inventory_pdf(project_name: str, rows: list[dict]) -> bytes:
    return pdf_report(
        f"Inventory report — {project_name}", "Stock position",
        kpis=[("Materials tracked", str(len(rows))),
              ("Below reorder level", str(sum(1 for r in rows if r["low"])))],
        sections=[{
            "heading": "Stock on site",
            "table": {"header": ["Material", "Available", "Unit", "Reserved", "Reorder at", "Location", "Status"],
                      "widths": [110, 45, 25, 40, 45, 60, 45],
                      "rows": [[r["material"], f"{r['available']:g}", r["unit"], f"{r.get('reserved', 0):g}",
                                f"{r['reorder_level']:g}", r.get("location") or "—",
                                "Reorder" if r["low"] else "OK"] for r in rows]},
        }],
        sources=["Inventory transactions recorded in BuildBudget AI"],
        limitations=["Damaged/wasted material is reported separately from available stock."],
    )


def progress_pdf(project, summary: dict, plan: dict, risks: list[str]) -> bytes:
    rows = plan.get("rows", [])
    return pdf_report(
        f"Project progress report — {project.name}", "Schedule and delivery",
        project_info=[("Project", project.name), ("Type", project.project_type.replace("_", " ").title()),
                      ("Start", project.start_date.isoformat() if project.start_date else "—"),
                      ("Expected completion", project.end_date.isoformat() if project.end_date else "—")],
        kpis=[("Tasks", str(len(rows))),
              ("Critical path", f"{plan.get('total_duration_days', 0)} working days"),
              ("Planned finish", plan.get("project_finish") or "—"),
              ("Overdue tasks", str(len(plan.get("overdue", [])))),
              ("Budget utilisation", f"{summary['utilization_pct']}%"
               if summary["utilization_pct"] is not None else "—")],
        sections=[{
            "heading": "Schedule",
            "table": {"header": ["Task", "Start", "Finish", "Days", "Progress", "Critical", "Status"],
                      "widths": [110, 45, 45, 25, 40, 40, 45],
                      "rows": [[r["name"], r["start"], r["end"], r["duration_days"],
                                f"{r['progress']:g}%", "Yes" if r["critical"] else "No",
                                "Overdue" if r["overdue"] else "On plan"] for r in rows]},
        }, {"heading": "Risks", "bullets": risks}],
        sources=["Task durations and progress entered on site"],
        limitations=["Calendar dates assume a 5-day working week.",
                     "Weather and approvals are not modelled as schedule constraints."],
    )


def supplier_pdf(material: str, quantity: float, rows: list[dict]) -> bytes:
    return pdf_report(
        f"Supplier comparison — {material}", f"Requirement: {quantity:g}",
        kpis=[("Quotations compared", str(len(rows))),
              ("Best delivered cost", money(rows[0]["total"]) if rows else "—")],
        sections=[{
            "heading": "Ranked by total delivered cost",
            "table": {"header": ["#", "Supplier", "Buy qty", "Unit price", "Base", "Tax", "Delivery",
                                 "Total", "Lead time", "Valid until", "Source"],
                      "widths": [10, 70, 35, 35, 40, 32, 35, 45, 35, 40, 45],
                      "rows": [[r["rank"], r["supplier"], f"{r['buy_quantity']:g}", money(r["unit_price"]),
                                money(r["base"]), money(r["tax"]), money(r["delivery"]), money(r["total"]),
                                f"{r['lead_time_days']} d" if r.get("lead_time_days") is not None else "—",
                                r["valid_until"] or "—", r["source_type"].replace("_", " ").title()]
                               for r in rows]},
        }],
        sources=["Stored supplier quotations only"],
        assumptions=["Total delivered cost = unit price × buy quantity (respecting MOQ) + tax + delivery."],
        limitations=["Expired quotations are ranked last.",
                     "Demonstration prices are synthetic and must not be treated as market rates."],
    )


def project_summary_pdf(project, summary: dict, items, expenses, plan: dict, labour: dict,
                        risks: list[str]) -> bytes:
    return pdf_report(
        f"Complete project summary — {project.name}", "One-page project review",
        project_info=[("Project", project.name), ("Type", project.project_type.replace("_", " ").title()),
                      ("Location", project.location or "—"), ("Status", project.status.title())],
        kpis=[("Approved budget", money(summary["approved_budget"])),
              ("Actual expenses", money(summary["actual_expenses"])),
              ("Remaining", money(summary["remaining_budget"])),
              ("BOQ estimate", money(summary["estimated_cost"])),
              ("Labour recorded", money(labour.get("total_cost", 0))),
              ("Planned finish", plan.get("project_finish") or "—")],
        sections=[
            {"heading": "Budget", "paragraphs": [summary.get("note", "")]},
            {"heading": "BOQ", "table": {"header": ["#", "Description", "Unit", "Qty", "Rate", "Total"],
                                          "widths": [12, 130, 25, 25, 40, 45],
                                          "rows": [[i.item_no, i.description, i.unit, f"{i.quantity:g}",
                                                    money(i.unit_rate), money(i.total)] for i in items]}},
            {"heading": "Recent expenses", "table": {"header": ["Date", "Category", "Vendor", "Amount"],
                                                     "widths": [45, 60, 110, 55],
                                                     "rows": [[e.expense_date.strftime("%d-%b-%Y"), e.category,
                                                               e.vendor or "—", money(e.amount)]
                                                              for e in expenses[:12]]}},
            {"heading": "Schedule", "table": {"header": ["Task", "Start", "Finish", "Progress"],
                                               "widths": [120, 55, 55, 50],
                                               "rows": [[r["name"], r["start"], r["end"], f"{r['progress']:g}%"]
                                                        for r in plan.get("rows", [])]}},
            {"heading": "Risks and observations", "bullets": risks},
        ],
        sources=["Project records in BuildBudget AI"],
        limitations=["Preliminary planning document, not a certified valuation."],
    )


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
HEADER_FILL = PatternFill("solid", fgColor="142139")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=14, color="142139")
THIN = Side(style="thin", color="D8DEE9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY_FMT = '"₹"#,##0.00'
DATE_FMT = "dd-mmm-yyyy"


def _title(ws, title: str, subtitle: str, span: int) -> int:
    ws.append([title])
    ws["A1"].font = TITLE_FONT
    ws.append([subtitle])
    ws["A2"].font = Font(italic=True, size=9, color="64748B")
    ws.append([DISCLAIMER])
    ws["A3"].font = Font(size=8, color="64748B")
    ws.append([])
    return 5


def _header(ws, row: int, headers: list[str]):
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h.replace("_", " ").title())
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[row].height = 28


def _style_body(ws, first_row: int, last_row: int, money_cols: set[int], date_cols: set[int]):
    for row in ws.iter_rows(min_row=first_row, max_row=last_row,
                            max_col=ws.max_column):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.column in money_cols:
                cell.number_format = MONEY_FMT
            if cell.column in date_cols and cell.value is not None:
                cell.number_format = DATE_FMT


def _widths(ws, widths: list[int]):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _finish(ws, header_row: int, last_row: int, name: str = "Data"):
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if last_row > header_row:
        ref = f"A{header_row}:{get_column_letter(ws.max_column)}{last_row}"
        try:
            ws.add_table(XLTable(displayName=name[:30], ref=ref))
        except Exception:  # noqa: BLE001 - autofilter is enough if the table name clashes
            ws.auto_filter.ref = ref


def boq_xlsx(project_name: str, items) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    r = _title(ws, f"Bill of Quantities — {project_name}", "Preliminary estimate", 10)
    headers = ["#", "Category", "Description", "Unit", "Qty", "Rate", "Material", "Labour",
               "Tax %", "Total", "Rate source", "Status"]
    _header(ws, r, headers)
    total_row_start = r + 1
    for it in items:
        ws.append([it.item_no, it.category, it.description, it.unit, float(it.quantity),
                   float(it.unit_rate), float(it.material_cost), float(it.labour_cost),
                   float(it.tax_pct), float(it.total), it.rate_source, it.approval_status])
    last = ws.max_row
    ws.append(["", "", "", "", "", "", "", "", "TOTAL", f"=SUM(J{total_row_start}:J{last})"])
    ws.cell(row=ws.max_row, column=9).font = Font(bold=True)
    ws.cell(row=ws.max_row, column=10).font = Font(bold=True, color="142139")
    _style_body(ws, total_row_start, ws.max_row, {6, 7, 8, 10}, set())
    _widths(ws, [6, 16, 46, 9, 10, 12, 13, 12, 8, 15, 16, 13])
    _finish(ws, r, ws.max_row - 1, "BOQTable")

    notes = wb.create_sheet("Notes")
    notes.append(["Assumptions and scope"])
    notes["A1"].font = TITLE_FONT
    for line in [
        "Only listed items are priced; structural work requires engineer-approved quantities.",
        "Rates come from user entry or a stored supplier quotation; the source is shown per row.",
        "Demonstration prices are synthetic sample data, not market prices.",
        DISCLAIMER,
    ]:
        notes.append([line])
    notes.column_dimensions["A"].width = 110
    for row in notes.iter_rows(min_row=2, max_row=notes.max_row):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def expenses_xlsx(project_name: str, expenses) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    r = _title(ws, f"Expense report — {project_name}", "Recorded expenses", 8)
    _header(ws, r, ["Date", "Category", "Description", "Vendor", "Invoice", "Payment", "Amount"])
    start = r + 1
    for e in expenses:
        ws.append([e.expense_date, e.category, e.description, e.vendor, e.invoice_no or "",
                   getattr(e, "payment_status", "paid"), float(e.amount)])
    last = ws.max_row
    ws.append(["", "", "", "", "", "TOTAL", f"=SUM(G{start}:G{last})"])
    ws.cell(row=ws.max_row, column=6).font = Font(bold=True)
    _style_body(ws, start, ws.max_row, {7}, {1})
    _widths(ws, [12, 18, 46, 26, 16, 12, 16])
    _finish(ws, r, ws.max_row - 1, "ExpenseTable")

    cats: dict[str, float] = {}
    for e in expenses:
        cats[e.category] = cats.get(e.category, 0) + float(e.amount)
    if cats:
        summary = wb.create_sheet("By category")
        summary.append(["Category", "Amount"])
        for c in summary[1]:
            c.fill = HEADER_FILL
            c.font = HEADER_FONT
        for k, v in sorted(cats.items(), key=lambda kv: -kv[1]):
            summary.append([k, round(v, 2)])
        for row in summary.iter_rows(min_row=2, max_row=summary.max_row):
            row[1].number_format = MONEY_FMT
        _widths(summary, [24, 18])
        chart = BarChart()
        chart.title = "Expenses by category"
        chart.y_axis.title = "Amount (INR)"
        data = Reference(summary, min_col=2, min_row=1, max_row=summary.max_row)
        cats_ref = Reference(summary, min_col=1, min_row=2, max_row=summary.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.height = 7.5
        chart.width = 16
        summary.add_chart(chart, "D2")
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def inventory_xlsx(project_name: str, rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    r = _title(ws, f"Inventory — {project_name}", "Stock position", 7)
    _header(ws, r, ["Material", "Available", "Unit", "Reserved", "Reorder level", "Location", "Status"])
    start = r + 1
    for row in rows:
        ws.append([row["material"], float(row["available"]), row["unit"], float(row.get("reserved", 0)),
                   float(row["reorder_level"]), row.get("location", ""),
                   "REORDER" if row["low"] else "OK"])
    _style_body(ws, start, ws.max_row, set(), set())
    for row in ws.iter_rows(min_row=start, max_row=ws.max_row, min_col=7, max_col=7):
        for cell in row:
            if cell.value == "REORDER":
                cell.fill = PatternFill("solid", fgColor="FEE2E2")
                cell.font = Font(bold=True, color="991B1B")
    _widths(ws, [30, 12, 10, 12, 14, 18, 12])
    _finish(ws, r, ws.max_row, "InventoryTable")
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def supplier_xlsx(material: str, rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"
    r = _title(ws, f"Supplier comparison — {material}", "Ranked by total delivered cost", 9)
    _header(ws, r, ["Rank", "Supplier", "Buy qty", "Unit price", "Base", "Tax", "Delivery",
                    "Total", "Valid until"])
    start = r + 1
    for row in rows:
        ws.append([row["rank"], row["supplier"], float(row["buy_quantity"]), float(row["unit_price"]),
                   float(row["base"]), float(row["tax"]), float(row["delivery"]), float(row["total"]),
                   row["valid_until"] or ""])
    _style_body(ws, start, ws.max_row, {4, 5, 6, 7, 8}, set())
    for row in ws.iter_rows(min_row=start, max_row=ws.max_row, min_col=9, max_col=9):
        for cell in row:
            if cell.value:
                cell.number_format = DATE_FMT
    _widths(ws, [7, 28, 11, 13, 13, 12, 12, 15, 14])
    _finish(ws, r, ws.max_row, "SupplierTable")
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def summary_xlsx(project_name: str, summary: dict, items, expenses, monthly: dict[str, float]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Project summary — {project_name}"])
    ws["A1"].font = TITLE_FONT
    ws.append([f"Generated {date.today():%d %B %Y} by BuildBudget AI"])
    ws.append([DISCLAIMER])
    ws.append([])
    ws.append(["Metric", "Value"])
    for c in ws[5]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    rows = [
        ("Approved budget", summary["approved_budget"]),
        ("Estimated cost (BOQ)", summary["estimated_cost"]),
        ("Actual expenses", summary["actual_expenses"]),
        ("Remaining budget", summary["remaining_budget"]),
        ("Utilisation %", summary["utilization_pct"] if summary["utilization_pct"] is not None else "No budget"),
        ("BOQ items", len(items)),
        ("Expense entries", len(expenses)),
    ]
    for label, value in rows:
        ws.append([label, value])
    for row in ws.iter_rows(min_row=6, max_row=ws.max_row):
        if isinstance(row[1].value, (int, float)):
            row[1].number_format = MONEY_FMT
    _widths(ws, [34, 22])
    ws.freeze_panes = "A6"

    if monthly:
        m = wb.create_sheet("Monthly spend")
        m.append(["Month", "Expenses"])
        for c in m[1]:
            c.fill = HEADER_FILL
            c.font = HEADER_FONT
        for k, v in sorted(monthly.items()):
            m.append([k, round(float(v), 2)])
        for row in m.iter_rows(min_row=2, max_row=m.max_row):
            row[1].number_format = MONEY_FMT
        chart = BarChart()
        chart.title = "Monthly expenses"
        chart.y_axis.title = "Amount (INR)"
        data = Reference(m, min_col=2, min_row=1, max_row=m.max_row)
        cats_ref = Reference(m, min_col=1, min_row=2, max_row=m.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.height = 8
        chart.width = 18
        m.add_chart(chart, "D2")
        _widths(m, [14, 16])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def boq_docx(project_name: str, items) -> bytes:
    import docx
    from docx.shared import Pt

    d = docx.Document()
    d.add_heading(f"Bill of Quantities — {project_name}", level=1)
    p = d.add_paragraph(DISCLAIMER)
    p.runs[0].font.size = Pt(8)
    table = d.add_table(rows=1, cols=6)
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(["#", "Description", "Unit", "Qty", "Rate (INR)", "Total (INR)"]):
        table.rows[0].cells[i].text = h
    for it in items:
        cells = table.add_row().cells
        cells[0].text = str(it.item_no)
        cells[1].text = it.description
        cells[2].text = it.unit
        cells[3].text = f"{it.quantity:g}"
        cells[4].text = f"{float(it.unit_rate):,.2f}"
        cells[5].text = f"{float(it.total):,.2f}"
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()
