import io
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from auth import get_request_token
import bigquery_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schema-audit", tags=["schema-audit"])

# ── Env helpers ────────────────────────────────────────────────────────────────

_ENV_MAP = {
    "dev": ("SCHEMA_AUDIT_DEV_SRC", "SCHEMA_AUDIT_DEV_TGT"),
    "uat": ("SCHEMA_AUDIT_UAT_SRC", "SCHEMA_AUDIT_UAT_TGT"),
    "prd": ("SCHEMA_AUDIT_PRD_SRC", "SCHEMA_AUDIT_PRD_TGT"),
}


def _get_datasets(env: str) -> tuple[str, str]:
    keys = _ENV_MAP.get(env.lower())
    if not keys:
        raise HTTPException(status_code=400, detail=f"Unknown environment: {env}")
    src = os.getenv(keys[0], "").strip()
    tgt = os.getenv(keys[1], "").strip()
    return src, tgt


def _get_src_tbl() -> str:
    return os.getenv("SCHEMA_AUDIT_SRC_TBL", "").strip()


# ── BigQuery helpers ───────────────────────────────────────────────────────────

def _fetch_table_list(token) -> list[str]:
    src_tbl = _get_src_tbl()
    if not src_tbl:
        return []
    sql = f"SELECT DISTINCT table_name FROM `{src_tbl}` WHERE is_streamed = 1 ORDER BY table_name"
    try:
        rows = bigquery_client.run_query(sql, token)
        return [r["table_name"] for r in rows if r.get("table_name")]
    except Exception as e:
        logger.error(f"Failed to fetch table list: {e}")
        return []


def _sanitize_table_names(names: list[str]) -> list[str]:
    """Allow only safe characters in table names to prevent SQL injection."""
    return [n for n in names if re.match(r"^[A-Za-z0-9_\-]+$", n)]


def _fetch_all_columns(dataset: str, table_names: list[str], token) -> dict[str, list[dict]] | None:
    """
    Returns {table_name: [columns]} for all tables found in the dataset.
    Returns None if dataset is not configured.
    Tables missing from the result simply don't exist in this dataset.
    """
    if not dataset or not table_names:
        return None

    safe_names = _sanitize_table_names(table_names)
    if not safe_names:
        return {}

    quoted = ", ".join(f"'{n}'" for n in safe_names)
    sql = f"""
        SELECT table_name, column_name, data_type, ordinal_position
        FROM `{dataset}`.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name IN ({quoted})
        ORDER BY table_name, ordinal_position
    """
    try:
        rows = bigquery_client.run_query(sql, token)
    except Exception as e:
        logger.error(f"INFORMATION_SCHEMA query failed for {dataset}: {e}")
        return None

    result: dict[str, list[dict]] = {}
    for row in rows:
        tbl = row["table_name"]
        result.setdefault(tbl, []).append({
            "column_name":      row["column_name"],
            "data_type":        row["data_type"],
            "ordinal_position": int(row["ordinal_position"]),
        })
    return result


# ── Schema comparison ──────────────────────────────────────────────────────────

def _describe_mismatch(type_diff: bool, pos_diff: bool) -> str:
    if type_diff and pos_diff:
        return "Type + Position Mismatch"
    if type_diff:
        return "Type Mismatch"
    if pos_diff:
        return "Position Mismatch"
    return ""


def _compare_table(
    table_name: str,
    src_cols: list[dict] | None,
    tgt_cols: list[dict] | None,
) -> tuple[dict, list[dict]]:
    """
    Returns:
      summary — one-row widget dict
      detail  — per-column dicts for Excel
    """
    src_missing = src_cols is None
    tgt_missing = tgt_cols is None

    src_list = src_cols or []
    tgt_list = tgt_cols or []

    src_map = {c["column_name"]: c for c in src_list}
    tgt_map = {c["column_name"]: c for c in tgt_list}

    col_count_diff = len(src_list) - len(tgt_list)

    detail: list[dict] = []
    col_name_mismatches = type_mismatches = pos_mismatches = 0

    # Columns present in SRC
    for col_name, sc in src_map.items():
        if col_name not in tgt_map:
            col_name_mismatches += 1
            detail.append({
                "src_col_name": col_name,
                "src_position": sc["ordinal_position"],
                "tgt_position": "—",
                "src_data_type": sc["data_type"],
                "tgt_data_type": "—",
                "description": "Source Only",
                "status": "Mismatch",
                "_sort": sc["ordinal_position"],
            })
        else:
            tc = tgt_map[col_name]
            type_diff = sc["data_type"].upper() != tc["data_type"].upper()
            pos_diff  = sc["ordinal_position"] != tc["ordinal_position"]
            if type_diff:
                type_mismatches += 1
            if pos_diff:
                pos_mismatches += 1
            desc   = _describe_mismatch(type_diff, pos_diff)
            status = "Mismatch" if (type_diff or pos_diff) else "Match"
            detail.append({
                "src_col_name": col_name,
                "src_position": sc["ordinal_position"],
                "tgt_position": tc["ordinal_position"],
                "src_data_type": sc["data_type"],
                "tgt_data_type": tc["data_type"],
                "description": desc,
                "status": status,
                "_sort": sc["ordinal_position"],
            })

    # Columns present only in TGT
    for col_name, tc in tgt_map.items():
        if col_name not in src_map:
            col_name_mismatches += 1
            detail.append({
                "src_col_name": "—",
                "src_position": "—",
                "tgt_position": tc["ordinal_position"],
                "src_data_type": "—",
                "tgt_data_type": tc["data_type"],
                "description": f"Target Only: {col_name}",
                "status": "Mismatch",
                "_sort": 999_999,  # push TGT-only rows to the end
            })

    detail.sort(key=lambda r: r["_sort"])

    has_mismatch = bool(col_name_mismatches or type_mismatches or pos_mismatches)

    summary = {
        "table_name":          table_name,
        "col_count_diff":      col_count_diff,
        "col_name_mismatches": col_name_mismatches,
        "type_mismatches":     type_mismatches,
        "pos_mismatches":      pos_mismatches,
        "has_mismatch":        has_mismatch,
        "src_missing":         src_missing,
        "tgt_missing":         tgt_missing,
    }
    return summary, detail


def _run_comparison(env: str, token) -> tuple[list[dict], dict[str, list[dict]]]:
    """
    Returns:
      summaries      — sorted list of summary dicts (mismatched first, then alphabetical)
      detail_by_tbl  — {table_name: [detail_rows]}
    """
    src_ds, tgt_ds = _get_datasets(env)
    table_names    = _fetch_table_list(token)

    src_all = _fetch_all_columns(src_ds, table_names, token)
    tgt_all = _fetch_all_columns(tgt_ds, table_names, token)

    summaries: list[dict] = []
    detail_by_tbl: dict[str, list[dict]] = {}

    for tbl in table_names:
        src_cols = src_all.get(tbl) if src_all is not None else None
        tgt_cols = tgt_all.get(tbl) if tgt_all is not None else None
        summary, detail = _compare_table(tbl, src_cols, tgt_cols)
        summaries.append(summary)
        detail_by_tbl[tbl] = detail

    # Sort: mismatched tables first (alphabetically), then matched (alphabetically)
    summaries.sort(key=lambda r: (0 if r["has_mismatch"] else 1, r["table_name"]))
    return summaries, detail_by_tbl


# ── Excel builder ──────────────────────────────────────────────────────────────

_BLUE_FILL  = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_WHITE_BOLD = Font(name="Courier New", size=11, bold=True, color="FFFFFF")
_DATA_FONT  = Font(name="Courier New", size=11)
_CENTER     = Alignment(horizontal="center", vertical="center")
_LEFT       = Alignment(horizontal="left",   vertical="center")


def _style_header(ws, headers: list[str], col_widths: list[int]) -> None:
    for col_idx, (header, width) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill      = _BLUE_FILL
        cell.font      = _WHITE_BOLD
        cell.alignment = _CENTER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 18


def _write_data_row(ws, row_idx: int, values: list) -> None:
    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.font      = _DATA_FONT
        cell.alignment = _LEFT


def _safe_sheet_name(name: str) -> str:
    """Truncate to 31 chars and strip characters invalid in Excel sheet names."""
    invalid = r'\/?*[]:'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name[:31]


def _build_excel(summaries: list[dict], detail_by_tbl: dict[str, list[dict]]) -> bytes:
    wb = Workbook()

    # ── Summary sheet ────────────────────────────────────────────────────────
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum.sheet_properties.tabColor = "4472C4"

    sum_headers = [
        "Table Name", "SRC Column Name", "SRC Position",
        "TGT Position", "SRC Data Type", "TGT Data Type",
        "Description", "Status",
    ]
    sum_widths = [30, 35, 16, 16, 25, 25, 38, 12]
    _style_header(ws_sum, sum_headers, sum_widths)

    row_idx = 2
    for summary in summaries:
        tbl  = summary["table_name"]
        rows = detail_by_tbl.get(tbl, [])
        for dr in rows:
            if dr["status"] == "Mismatch":
                _write_data_row(ws_sum, row_idx, [
                    tbl,
                    dr["src_col_name"],
                    dr["src_position"],
                    dr["tgt_position"],
                    dr["src_data_type"],
                    dr["tgt_data_type"],
                    dr["description"],
                    dr["status"],
                ])
                row_idx += 1

    ws_sum.freeze_panes = "A2"

    # ── Per-table sheets ─────────────────────────────────────────────────────
    tbl_headers = [
        "SRC Column Name", "SRC Position", "TGT Position",
        "SRC Data Type", "TGT Data Type", "Description", "Status",
    ]
    tbl_widths = [35, 16, 16, 25, 25, 38, 12]

    # Iterate summaries so order matches summary sort (mismatched first)
    for summary in summaries:
        tbl  = summary["table_name"]
        rows = detail_by_tbl.get(tbl, [])

        ws = wb.create_sheet(title=_safe_sheet_name(tbl))
        ws.sheet_properties.tabColor = "4472C4"
        _style_header(ws, tbl_headers, tbl_widths)

        for r_idx, dr in enumerate(rows, start=2):
            _write_data_row(ws, r_idx, [
                dr["src_col_name"],
                dr["src_position"],
                dr["tgt_position"],
                dr["src_data_type"],
                dr["tgt_data_type"],
                dr["description"],
                dr["status"],
            ])
        ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/{env}")
async def get_schema_audit(
    env: str,
    token: Optional[str] = Depends(get_request_token),
):
    """Widget summary endpoint — one row per table."""
    configured = bool(_get_src_tbl() and all(_get_datasets(env)))
    if not configured:
        return {"configured": False, "tables": []}

    try:
        summaries, _ = _run_comparison(env, token)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schema audit failed for env={env}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"configured": True, "tables": summaries}


@router.get("/{env}/download")
async def download_schema_audit(
    env: str,
    token: Optional[str] = Depends(get_request_token),
):
    """Excel download endpoint."""
    if not _get_src_tbl():
        raise HTTPException(status_code=503, detail="SCHEMA_AUDIT_SRC_TBL is not configured.")
    src_ds, tgt_ds = _get_datasets(env)
    if not src_ds or not tgt_ds:
        raise HTTPException(status_code=503, detail=f"SCHEMA_AUDIT_{env.upper()}_SRC / _TGT not configured.")

    try:
        summaries, detail_by_tbl = _run_comparison(env, token)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schema audit download failed for env={env}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    excel_bytes = _build_excel(summaries, detail_by_tbl)
    filename    = f"schema_mismatch_{env}.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
