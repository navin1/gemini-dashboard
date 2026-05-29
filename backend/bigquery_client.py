import os
import re
import logging
from google.cloud import bigquery
from auth import get_bq_credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ── Scorecard SQL case-insensitive normalizer ─────────────────────────────────
# The scorecard queries hardcode string literals for a small set of categorical
# columns (Project_Class, FOB, BillType).  If the data uses different casing
# (e.g. 'CAPITAL' instead of 'Capital') every CASE WHEN / WHERE IN silently
# returns 0.  Wrapping comparisons in LOWER(TRIM()) makes them case- and
# whitespace-insensitive at zero query-cost.

_SCORECARD_CATEGORICAL: frozenset[str] = frozenset({"BillType"})


def _ci_scorecard_sql(sql: str) -> str:
    """
    Rewrite hardcoded string comparisons for known categorical columns to be
    case-insensitive.

    Transforms applied (only for columns in _SCORECARD_CATEGORICAL):
      col IN ('Val1', 'Val2')   →  LOWER(TRIM(col)) IN ('val1', 'val2')
      col = 'Value'             →  LOWER(TRIM(col)) = 'value'
      CASE WHEN col='Value'     →  CASE WHEN LOWER(TRIM(col)) = 'value'
    """
    cats_pat = "|".join(re.escape(c) for c in _SCORECARD_CATEGORICAL)

    # IN clause: col IN ('A','B') → LOWER(TRIM(col)) IN ('a','b')
    def _rewrite_in(m: re.Match) -> str:
        col = m.group(1)
        raw_vals = m.group(2)
        lowered = re.sub(r"'([^']*)'", lambda x: f"'{x.group(1).lower()}'", raw_vals)
        return f"LOWER(TRIM({col})) IN ({lowered})"

    sql = re.sub(
        rf"\b({cats_pat})\s+IN\s*\((\s*'[^']*'(?:\s*,\s*'[^']*')*\s*)\)",
        _rewrite_in,
        sql,
        flags=re.IGNORECASE,
    )

    # Equality: col = 'Value' → LOWER(TRIM(col)) = 'value'
    def _rewrite_eq(m: re.Match) -> str:
        col = m.group(1)
        val = m.group(2).lower()
        return f"LOWER(TRIM({col})) = '{val}'"

    sql = re.sub(
        rf"\b({cats_pat})\s*=\s*'([^']*)'",
        _rewrite_eq,
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def _ci(queries: dict[str, str]) -> dict[str, str]:
    """Apply _ci_scorecard_sql to every query in a dict."""
    return {k: _ci_scorecard_sql(v) for k, v in queries.items()}

# Project where the data lives (used in table references only)
PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID") or "mygclearning"
DATASET    = os.getenv("BIGQUERY_DATASET")    or "test"
TABLE      = os.getenv("BIGQUERY_TABLE")      or "one"

def _parse_table_refs() -> list[str]:
    """Parse BIGQUERY_TABLES (comma-separated project.dataset.table) or fall back to legacy vars."""
    raw = (os.getenv("BIGQUERY_TABLES") or "").strip()
    if raw:
        return [t.strip().strip("`") for t in raw.split(",") if t.strip()]
    return [f"{PROJECT_ID}.{DATASET}.{TABLE}"]

TABLE_REFS: list[str] = _parse_table_refs()
TABLE_REF = f"`{TABLE_REFS[0]}`"  # primary table (backtick-quoted) used by scorecard queries

# Project_Class in the data uses compound codes (CAPITAL-LABOR, EXPENSE-DIV, OPEX-TECH, etc.)
# rather than the simple 'Capital'/'Expense' labels the scorecards originally expected.
_PC_IS_CAPITAL = "Project_Class LIKE 'CAPITAL%'"
_PC_IS_EXPENSE = "(Project_Class LIKE 'EXPENSE%' OR Project_Class = 'OPEX-TECH')"
_PC_FILTER     = f"({_PC_IS_CAPITAL} OR {_PC_IS_EXPENSE})"
_PC_LABEL      = f"CASE WHEN {_PC_IS_CAPITAL} THEN 'Capital' ELSE 'Expense' END"


def build_schema_context(token: str | None = None) -> str:
    """Fetch live column schemas and categorical sample values for all configured tables.

    For every STRING column with ≤ 60 distinct values (i.e. a categorical column),
    the context includes the actual values so the model knows valid filter literals
    before writing SQL — eliminating the wrong-value problem at the source.
    """
    client = _client(token)
    sections = []
    for ref in TABLE_REFS:
        try:
            tbl = client.get_table(ref)

            # Collect STRING columns for sample-value enrichment.
            str_cols = [
                f.name for f in tbl.schema
                if f.field_type in ("STRING", "BYTES") and f.mode != "REPEATED"
            ]

            # One UNNEST query fetches cardinality + distinct samples for all string
            # columns in a single BQ pass.  Only categorical columns (≤ 60 distinct
            # values) get their values included — high-cardinality columns (names,
            # IDs, free-text) are omitted to keep the context compact.
            sample_vals: dict[str, list[str]] = {}
            if str_cols:
                structs = ", ".join(
                    f"STRUCT('{c}' AS c, CAST(`{c}` AS STRING) AS v)"
                    for c in str_cols
                )
                sample_sql = (
                    f"SELECT col, vals FROM ("
                    f"SELECT t.c AS col, APPROX_COUNT_DISTINCT(t.v) AS cardinality,"
                    f" STRING_AGG(DISTINCT t.v, '|||' ORDER BY t.v LIMIT 25) AS vals"
                    f" FROM `{ref}`, UNNEST([{structs}]) AS t"
                    f" WHERE t.v IS NOT NULL AND TRIM(t.v) NOT IN ('', '0')"
                    f" GROUP BY t.c) WHERE cardinality <= 60"
                )
                try:
                    rows = run_query(sample_sql, token)
                    for row in rows:
                        if row.get("vals"):
                            sample_vals[row["col"]] = [
                                v.strip() for v in str(row["vals"]).split("|||") if v.strip()
                            ]
                except Exception as exc:
                    logger.warning(f"build_schema_context: sample-value fetch failed: {exc}")

            lines = []
            for field in tbl.schema:
                desc = f" -- {field.description}" if field.description else ""
                mode = " REPEATED" if field.mode == "REPEATED" else ""
                vals = sample_vals.get(field.name, [])
                val_hint = f"  -- values: {', '.join(repr(v) for v in vals)}" if vals else ""
                lines.append(f"  {field.name} {field.field_type}{mode}{desc}{val_hint}")

            body = "\n".join(lines) if lines else "  (no columns retrieved)"
            sections.append(f"BigQuery table: `{ref}`\n{body}")
        except Exception as exc:
            sections.append(f"BigQuery table: `{ref}`\n  (schema unavailable: {exc})")
    return "\n\n".join(sections)

# Project where query jobs run — this is where BigQuery billing goes.
# Resolution order: explicit BQ_JOB_PROJECT_ID → Cloud Run auto-inject →
# GCP_PROJECT_ID from .env → fallback to data project.
JOB_PROJECT_ID = (
    os.getenv("BQ_JOB_PROJECT_ID")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("GCP_PROJECT_ID")
    or PROJECT_ID
)


def _client(token: str | None = None) -> bigquery.Client:
    return bigquery.Client(project=JOB_PROJECT_ID, credentials=get_bq_credentials(token))


def run_query(sql: str, token: str | None = None) -> list[dict]:
    client = _client(token)
    job = client.query(sql)
    rows = job.result()
    result = []
    for row in rows:
        record = {}
        for key, value in row.items():
            # Convert non-serializable types
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
            elif value is None:
                record[key] = None
            else:
                record[key] = value
        result.append(record)
    return result


# ── Pre-built scorecard queries ───────────────────────────────────────────────

FTE_SCORECARD_QUERIES = {
    "kpi_ytd_spend": f"""
        SELECT
            SUM(YTD_Spend) AS spend_to_date,
            SUM(YTD_Spend) AS commit_spend,
            SAFE_DIVIDE(SUM(YTD_Spend), NULLIF(SUM(SAFE_CAST(Budget AS FLOAT64)), 0)) * 100 AS pct_spend
        FROM {TABLE_REF}
    """,

    "monthly_capital_expense": f"""
        SELECT month, Project_Class, SUM(Dollars) AS Dollars
        FROM (
            SELECT month, m_ord, {_PC_LABEL} AS Project_Class, Dollars
            FROM (
                SELECT 'Jan' AS month, 1 AS m_ord, Project_Class, Period_01_Dollars AS Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Feb',2, Project_Class, Period_02_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Mar',3, Project_Class, Period_03_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Apr',4, Project_Class, Period_04_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'May',5, Project_Class, Period_05_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Jun',6, Project_Class, Period_06_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Jul',7, Project_Class, Period_07_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Aug',8, Project_Class, Period_08_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Sep',9, Project_Class, Period_09_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Oct',10, Project_Class, Period_10_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Nov',11, Project_Class, Period_11_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Dec',12, Project_Class, Period_12_Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
            )
        )
        GROUP BY month, Project_Class ORDER BY MIN(m_ord)
    """,

    "monthly_fte": f"""
        SELECT month, SUM(FTP) AS FTP, SUM(Dollars) AS Dollars
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord, Period_01_FTP AS FTP, Period_01_Dollars AS Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,Period_02_FTP,Period_02_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,Period_03_FTP,Period_03_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,Period_04_FTP,Period_04_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,Period_05_FTP,Period_05_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,Period_06_FTP,Period_06_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,Period_07_FTP,Period_07_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,Period_08_FTP,Period_08_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,Period_09_FTP,Period_09_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,Period_10_FTP,Period_10_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,Period_11_FTP,Period_11_Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,Period_12_FTP,Period_12_Dollars FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,

    "hierarchy_table": f"""
        SELECT
            ResourceVP AS Hierarchy,
            Resource_Manager AS Leader,
            COUNT(DISTINCT RACFID_PO) AS HC,
            ROUND(AVG(FTE_AVERAGE), 1) AS FTE,
            SUM(eff_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Expense_Pct,
            SUM(eff_spend) AS Committed_Spend
        FROM (
            SELECT *,
                COALESCE(NULLIF(YTD_Spend,0),
                    COALESCE(Period_01_Dollars,0)+COALESCE(Period_02_Dollars,0)+COALESCE(Period_03_Dollars,0)+
                    COALESCE(Period_04_Dollars,0)+COALESCE(Period_05_Dollars,0)+COALESCE(Period_06_Dollars,0)+
                    COALESCE(Period_07_Dollars,0)+COALESCE(Period_08_Dollars,0)+COALESCE(Period_09_Dollars,0)+
                    COALESCE(Period_10_Dollars,0)+COALESCE(Period_11_Dollars,0)+COALESCE(Period_12_Dollars,0)) AS eff_spend
            FROM {TABLE_REF}
            WHERE ResourceVP IS NOT NULL
        )
        GROUP BY ResourceVP, Resource_Manager
        ORDER BY Spend_to_Date DESC
    """,

    "capital_expense_donut": f"""
        SELECT {_PC_LABEL} AS type, SUM(YTD_Spend) AS amount
        FROM {TABLE_REF}
        WHERE {_PC_FILTER}
        GROUP BY 1
    """,

    "monthly_cap_exp_ftp": f"""
        SELECT month,
            SUM(CASE WHEN {_PC_IS_CAPITAL} THEN Dollars ELSE 0 END) AS Capital,
            SUM(CASE WHEN {_PC_IS_EXPENSE} THEN Dollars ELSE 0 END) AS Expense,
            SUM(FTP) AS FTP
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord,Project_Class,Period_01_Dollars AS Dollars,Period_01_FTP AS FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,Project_Class,Period_02_Dollars,Period_02_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,Project_Class,Period_03_Dollars,Period_03_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,Project_Class,Period_04_Dollars,Period_04_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,Project_Class,Period_05_Dollars,Period_05_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,Project_Class,Period_06_Dollars,Period_06_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,Project_Class,Period_07_Dollars,Period_07_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,Project_Class,Period_08_Dollars,Period_08_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,Project_Class,Period_09_Dollars,Period_09_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,Project_Class,Period_10_Dollars,Period_10_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,Project_Class,Period_11_Dollars,Period_11_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,Project_Class,Period_12_Dollars,Period_12_FTP FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,
}

VENDOR_SCORECARD_QUERIES = {
    "vendor_table": f"""
        SELECT
            Vendor,
            ROUND(SUM(Period_01_FTP+Period_02_FTP+Period_03_FTP+Period_04_FTP+Period_05_FTP+Period_06_FTP+Period_07_FTP+Period_08_FTP+Period_09_FTP+Period_10_FTP+Period_11_FTP+Period_12_FTP), 1) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            SUM(YTD_Spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Expense_Pct,
            SUM(YTD_Spend) AS Committed_Spend
        FROM {TABLE_REF}
        WHERE Vendor IS NOT NULL AND Vendor != ''
        GROUP BY Vendor
        ORDER BY Spend_to_Date DESC
    """,

    "offshore_onshore_bar": f"""
        SELECT FOB, ROUND(SUM(FTE_AVERAGE),1) AS FTE
        FROM {TABLE_REF}
        WHERE FOB IS NOT NULL AND TRIM(FOB) NOT IN ('', '0')
        GROUP BY FOB
        ORDER BY FTE DESC
        LIMIT 10
    """,

    "billtype_bar": f"""
        SELECT BillType, SUM(YTD_Spend) AS Spend
        FROM {TABLE_REF}
        WHERE BillType IN ('TM','Fixed Fee')
        GROUP BY BillType
    """,

    "monthly_vendor_spend": f"""
        SELECT month, BillType, SUM(Dollars) AS Dollars
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord, BillType, Period_01_Dollars AS Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Feb',2,BillType,Period_02_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Mar',3,BillType,Period_03_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Apr',4,BillType,Period_04_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'May',5,BillType,Period_05_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Jun',6,BillType,Period_06_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Jul',7,BillType,Period_07_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Aug',8,BillType,Period_08_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Sep',9,BillType,Period_09_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Oct',10,BillType,Period_10_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Nov',11,BillType,Period_11_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Dec',12,BillType,Period_12_Dollars FROM {TABLE_REF} WHERE BillType IN ('TM','Fixed Fee')
        )
        GROUP BY month, BillType ORDER BY MIN(m_ord)
    """,

    "spend_by_tier_monthly": f"""
        SELECT month, Resource_Category, Dollars
        FROM (
            SELECT month, Resource_Category, SUM(Dollars) AS Dollars, MIN(m_ord) AS _sort
            FROM (
                SELECT 'Jan' AS month,1 AS m_ord,Resource_Category,Period_01_Dollars AS Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Feb',2,Resource_Category,Period_02_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Mar',3,Resource_Category,Period_03_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Apr',4,Resource_Category,Period_04_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'May',5,Resource_Category,Period_05_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Jun',6,Resource_Category,Period_06_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Jul',7,Resource_Category,Period_07_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Aug',8,Resource_Category,Period_08_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Sep',9,Resource_Category,Period_09_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Oct',10,Resource_Category,Period_10_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Nov',11,Resource_Category,Period_11_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Dec',12,Resource_Category,Period_12_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
            )
            GROUP BY month, Resource_Category
        )
        WHERE Dollars > 0
        ORDER BY _sort
    """,

    "monthly_cap_exp_ftp": f"""
        SELECT month,
            SUM(CASE WHEN {_PC_IS_CAPITAL} THEN Dollars ELSE 0 END) AS Capital,
            SUM(CASE WHEN {_PC_IS_EXPENSE} THEN Dollars ELSE 0 END) AS Expense,
            SUM(FTP) AS FTP
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord,Project_Class,Period_01_Dollars AS Dollars,Period_01_FTP AS FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,Project_Class,Period_02_Dollars,Period_02_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,Project_Class,Period_03_Dollars,Period_03_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,Project_Class,Period_04_Dollars,Period_04_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,Project_Class,Period_05_Dollars,Period_05_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,Project_Class,Period_06_Dollars,Period_06_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,Project_Class,Period_07_Dollars,Period_07_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,Project_Class,Period_08_Dollars,Period_08_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,Project_Class,Period_09_Dollars,Period_09_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,Project_Class,Period_10_Dollars,Period_10_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,Project_Class,Period_11_Dollars,Period_11_FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,Project_Class,Period_12_Dollars,Period_12_FTP FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,

    "vendor_kpis": f"""
        SELECT
            COUNT(DISTINCT Vendor)    AS Total_Vendors,
            COUNT(DISTINCT RACFID_PO) AS Total_Resources,
            SUM(YTD_Spend)            AS Total_Cost
        FROM {TABLE_REF}
        WHERE Vendor IS NOT NULL
          AND LOWER(TRIM(Vendor)) != 'internal'
    """,

    "vendor_resource_count": f"""
        SELECT Vendor, COUNT(DISTINCT RACFID_PO) AS Resource_Count
        FROM {TABLE_REF}
        WHERE Vendor IS NOT NULL
          AND LOWER(TRIM(Vendor)) != 'internal'
        GROUP BY Vendor
        ORDER BY Resource_Count DESC
        LIMIT 15
    """,

    "tier_breakdown": f"""
        SELECT
            Resource_Category AS Tier,
            COUNT(DISTINCT RACFID_PO) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS FixedFee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Expense_Pct,
            SUM(YTD_Spend) AS Spend_to_Date
        FROM {TABLE_REF}
        WHERE Resource_Category IS NOT NULL
        GROUP BY Resource_Category
        ORDER BY Spend_to_Date DESC
    """,
}

SHARED_QUERIES = {
    "tier_breakdown": VENDOR_SCORECARD_QUERIES["tier_breakdown"],
    "spend_by_tier_monthly": VENDOR_SCORECARD_QUERIES["spend_by_tier_monthly"],
    "monthly_vendor_spend": VENDOR_SCORECARD_QUERIES["monthly_vendor_spend"],
}

HIERARCHY_SCORECARD_QUERIES = {
    "hierarchy_drill": f"""
        SELECT
            ResourceVP,
            Vendor,
            Resource_Manager AS Leader,
            COUNT(DISTINCT RACFID_PO) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            SUM(eff_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Expense_Pct
        FROM (
            SELECT *,
                COALESCE(NULLIF(YTD_Spend,0),
                    COALESCE(Period_01_Dollars,0)+COALESCE(Period_02_Dollars,0)+COALESCE(Period_03_Dollars,0)+
                    COALESCE(Period_04_Dollars,0)+COALESCE(Period_05_Dollars,0)+COALESCE(Period_06_Dollars,0)+
                    COALESCE(Period_07_Dollars,0)+COALESCE(Period_08_Dollars,0)+COALESCE(Period_09_Dollars,0)+
                    COALESCE(Period_10_Dollars,0)+COALESCE(Period_11_Dollars,0)+COALESCE(Period_12_Dollars,0)) AS eff_spend
            FROM {TABLE_REF}
            WHERE ResourceVP IS NOT NULL
        )
        GROUP BY ResourceVP, Vendor, Resource_Manager
        ORDER BY ResourceVP, Spend_to_Date DESC
    """,

    "spend_by_tier_monthly": f"""
        SELECT month, Resource_Category, Dollars
        FROM (
            SELECT month, Resource_Category, SUM(Dollars) AS Dollars, MIN(m_ord) AS _sort
            FROM (
                SELECT 'Jan' AS month,1 AS m_ord,Resource_Category,Period_01_Dollars AS Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Feb',2,Resource_Category,Period_02_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Mar',3,Resource_Category,Period_03_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Apr',4,Resource_Category,Period_04_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'May',5,Resource_Category,Period_05_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Jun',6,Resource_Category,Period_06_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Jul',7,Resource_Category,Period_07_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Aug',8,Resource_Category,Period_08_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Sep',9,Resource_Category,Period_09_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Oct',10,Resource_Category,Period_10_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Nov',11,Resource_Category,Period_11_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
                UNION ALL SELECT 'Dec',12,Resource_Category,Period_12_Dollars FROM {TABLE_REF} WHERE Resource_Category IS NOT NULL
            )
            GROUP BY month, Resource_Category
        )
        WHERE Dollars > 0
        ORDER BY _sort
    """,
}

# Apply case-insensitive normalization to all scorecard query dicts.
# SHARED_QUERIES is a subset of VENDOR_SCORECARD_QUERIES values copied at
# definition time, so it must be transformed independently.
FTE_SCORECARD_QUERIES       = _ci(FTE_SCORECARD_QUERIES)
VENDOR_SCORECARD_QUERIES    = _ci(VENDOR_SCORECARD_QUERIES)
SHARED_QUERIES              = _ci(SHARED_QUERIES)
HIERARCHY_SCORECARD_QUERIES = _ci(HIERARCHY_SCORECARD_QUERIES)
