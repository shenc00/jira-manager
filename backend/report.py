"""Manager-update report: gather June (current-month) work and render a slide.

Structure: open Epics assigned to me -> their Stories -> Sub-tasks whose Target
Completion Date falls in the chosen month. Each sub-task gets a RAG status; each
Story shows a progress summary. Rendered as a single-table PowerPoint slide.
"""
from __future__ import annotations

import calendar
import io
from datetime import date

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from . import fields as fields_mod
from .jira_client import JiraClient, adf_to_text

START_DATE_FIELD = "customfield_10015"

# RAG palette (R, G, B)
GREEN = RGBColor(0x36, 0xB3, 0x7E)
AMBER = RGBColor(0xFF, 0x99, 0x1F)
RED = RGBColor(0xDE, 0x35, 0x0B)
BLUE = RGBColor(0x05, 0x29, 0xCC)
GREY = RGBColor(0x97, 0xA0, 0xAF)
HEADER_BG = RGBColor(0x05, 0x29, 0xCC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK = RGBColor(0x17, 0x2B, 0x4D)


def rag_status(name: str, category: str, end, today: date | None = None):
    """Return (label, colour) RAG assessment for a sub-task."""
    today = today or date.today()
    if (name or "").lower() == "cancelled":
        return "Cancelled", GREY
    if category == "done":
        return "Done", BLUE
    wd = fields_mod.working_days_until(end, today)
    if wd is None:
        return "No date", GREY
    if wd < 0:
        return "Overdue", RED
    if wd <= 3:
        return "At Risk", AMBER
    return "On Track", GREEN


def _one_line(text: str, limit: int = 160) -> str:
    line = (text or "").strip().replace("\r", " ")
    line = line.split("\n")[0].strip()
    return line[:limit] + ("…" if len(line) > limit else "")


def _in_month(value, year: int, month: int) -> bool:
    d = fields_mod.to_date(value)
    return bool(d and d.year == year and d.month == month)


def gather(client: JiraClient, year: int, month: int,
           assignee: str | None = None) -> list[dict]:
    """Collect epics -> stories -> in-month sub-tasks with RAG status.

    ``assignee`` is an accountId; defaults to the current user.
    """
    today = date.today()
    tgt = fields_mod.TARGET_COMPLETION_FIELD
    who = "currentUser()" if not assignee else f'"{assignee}"'
    epics = client.search(
        f"assignee = {who} AND issuetype = Epic AND statusCategory != Done "
        "ORDER BY summary",
        fields=["summary", "description", "status"],
    )
    result: list[dict] = []
    for e in epics:
        ek, ef = e["key"], e["fields"]
        stories_out = []
        children = client.search(
            f'parent = "{ek}" ORDER BY summary',
            fields=["summary", "issuetype", "status", "description"],
        )
        for ch in children:
            cf = ch["fields"]
            if (cf.get("issuetype") or {}).get("subtask"):
                continue
            ck = ch["key"]
            subs = client.search(
                f'parent = "{ck}" ORDER BY summary',
                fields=["summary", "status", "assignee", START_DATE_FIELD, tgt],
            )
            month_subs = [s for s in subs if _in_month(s["fields"].get(tgt), year, month)]
            if not month_subs:
                continue
            total = len(subs)
            done = sum(
                1 for s in subs
                if ((s["fields"].get("status") or {}).get("statusCategory") or {})
                .get("key") == "done"
            )
            rows = []
            for s in month_subs:
                sf = s["fields"]
                status_name = (sf.get("status") or {}).get("name", "")
                cat = ((sf.get("status") or {}).get("statusCategory") or {}).get("key", "")
                end = sf.get(tgt)
                label, colour = rag_status(status_name, cat, end, today)
                rows.append({
                    "key": s["key"],
                    "summary": sf.get("summary", ""),
                    "start": str(sf.get(START_DATE_FIELD) or "")[:10] or "—",
                    "end": str(end or "")[:10] or "—",
                    "status": status_name,
                    "rag": label,
                    "ragColor": "#%02X%02X%02X" % (colour[0], colour[1], colour[2]),
                    "_color": colour,
                    "who": (sf.get("assignee") or {}).get("displayName", "Unassigned"),
                })
            stories_out.append({
                "key": ck,
                "summary": cf.get("summary", ""),
                "description": _one_line(adf_to_text(cf.get("description"))),
                "progress": f"{done}/{total} sub-tasks done",
                "subs": rows,
            })
        if stories_out:
            result.append({
                "key": ek,
                "summary": ef.get("summary", ""),
                "description": _one_line(adf_to_text(ef.get("description"))),
                "stories": stories_out,
            })
    return result


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


# --- PowerPoint rendering --------------------------------------------------

COLS = ["Epic", "Story / Sub-task", "Start date", "Target end", "Status", "Responsible"]
COL_WIDTHS = [2.6, 4.3, 1.2, 1.2, 1.3, 2.0]  # inches (total ~12.6 on 13.33 slide)


def _set_cell(cell, runs, *, bold=False, size=9, color=DARK, fill=None,
              align=PP_ALIGN.LEFT):
    """runs: list of (text, bold) lines, or a plain string."""
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.margin_left = Inches(0.05)
    cell.margin_right = Inches(0.05)
    cell.margin_top = Inches(0.02)
    cell.margin_bottom = Inches(0.02)
    if fill is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
    tf = cell.text_frame
    tf.word_wrap = True
    lines = runs if isinstance(runs, list) else [(runs, bold)]
    for i, (text, b) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = b
        r.font.color.rgb = color


def build_pptx(epics: list[dict], year: int, month: int,
               owner: str | None = None) -> bytes:
    title_suffix = f"  —  {owner}" if owner else ""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Title
    title_box = slide.shapes.add_textbox(Inches(0.4), Inches(0.2), Inches(12.5), Inches(0.7))
    tp = title_box.text_frame.paragraphs[0]
    run = tp.add_run()
    run.text = f"Monthly Report – {month_label(year, month)}{title_suffix}"
    run.font.size = Pt(24)
    run.font.bold = True
    run.font.color.rgb = HEADER_BG

    # Flatten to rows, tracking epic/story spans
    flat = []  # (epic, story, sub) with markers for first-of-group
    for ep in epics:
        e_first = True
        e_rowspan = sum(len(st["subs"]) for st in ep["stories"])
        for st in ep["stories"]:
            s_first = True
            for sub in st["subs"]:
                flat.append({
                    "epic": ep, "story": st, "sub": sub,
                    "e_first": e_first, "e_span": e_rowspan,
                    "s_first": s_first, "s_span": len(st["subs"]),
                })
                e_first = False
                s_first = False

    n_rows = len(flat) + 1  # + header
    if not flat:
        box = slide.shapes.add_textbox(Inches(0.4), Inches(1.2), Inches(12), Inches(1))
        box.text_frame.paragraphs[0].add_run().text = (
            f"No sub-tasks with a Target Completion Date in {month_label(year, month)}."
        )
        out = io.BytesIO(); prs.save(out); return out.getvalue()

    rows_h = min(0.55, max(0.28, 5.8 / len(flat)))
    table_h = Inches(0.4 + rows_h * len(flat))
    gf = slide.shapes.add_table(n_rows, len(COLS), Inches(0.4), Inches(1.05),
                                Inches(sum(COL_WIDTHS)), table_h)
    table = gf.table
    table.first_row = True
    for i, w in enumerate(COL_WIDTHS):
        table.columns[i].width = Inches(w)

    # Header
    for c, name in enumerate(COLS):
        _set_cell(table.cell(0, c), name, bold=True, size=10, color=WHITE,
                  fill=HEADER_BG, align=PP_ALIGN.CENTER)

    # Body
    for idx, row in enumerate(flat):
        r = idx + 1
        ep, st, sub = row["epic"], row["story"], row["sub"]
        # Epic cell (filled on first row, merged across span)
        if row["e_first"]:
            _set_cell(table.cell(r, 0),
                      [(f'{ep["key"]}: {ep["summary"]}', True),
                       (ep["description"], False)] if ep["description"]
                      else [(f'{ep["key"]}: {ep["summary"]}', True)],
                      size=9)
        else:
            _set_cell(table.cell(r, 0), "", size=9)
        # Story / sub-task cell: story header (first row of story) + sub-task line
        story_lines = []
        if row["s_first"]:
            story_lines.append((f'{st["key"]}: {st["summary"]}  ({st["progress"]})', True))
            if st.get("description"):
                story_lines.append((st["description"], False))
        story_lines.append((f'↳ {sub["key"]}: {sub["summary"]}', False))
        _set_cell(table.cell(r, 1), story_lines, size=9)
        _set_cell(table.cell(r, 2), sub["start"], size=9, align=PP_ALIGN.CENTER)
        _set_cell(table.cell(r, 3), sub["end"], size=9, align=PP_ALIGN.CENTER)
        _set_cell(table.cell(r, 4), [(sub["rag"], True)], size=9, color=WHITE,
                  fill=sub["_color"], align=PP_ALIGN.CENTER)
        _set_cell(table.cell(r, 5), sub["who"], size=9)

    # Merge epic cells per group
    r = 1
    for ep in epics:
        span = sum(len(st["subs"]) for st in ep["stories"])
        if span > 1:
            table.cell(r, 0).merge(table.cell(r + span - 1, 0))
        r += span

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
