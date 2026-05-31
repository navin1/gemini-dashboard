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

_SCORECARD_CATEGORICAL: frozenset[str] = frozenset({"billtype"})


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
TABLE      = os.getenv("BIGQUERY_TABLE")      or "one_v"

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
_PC_IS_CAPITAL = "project_class LIKE 'CAPITAL%'"
_PC_IS_EXPENSE = "(project_class LIKE 'EXPENSE%' OR project_class = 'OPEX-TECH')"
_PC_FILTER     = f"({_PC_IS_CAPITAL} OR {_PC_IS_EXPENSE})"
_PC_LABEL      = f"CASE WHEN {_PC_IS_CAPITAL} THEN 'Capital' ELSE 'Expense' END"


def build_schema_context(token: str | None = None) -> str:
    """Fetch live column schemas for all configured tables from BigQuery."""
    client = _client(token)
    sections = []
    for ref in TABLE_REFS:
        try:
            tbl = client.get_table(ref)
            lines = []
            for field in tbl.schema:
                desc = f"  -- {field.description}" if field.description else ""
                mode = " REPEATED" if field.mode == "REPEATED" else ""
                lines.append(f"  {field.name} {field.field_type}{mode}{desc}")
            body = "\n".join(lines) if lines else "  (no columns retrieved)"
            sections.append(f"BigQuery table: `{ref}`\n{body}")
        except Exception as exc:
            sections.append(f"BigQuery table: `{ref}`\n  (schema unavailable: {exc})")
    return "\n\n".join(sections)


def fetch_column_sample_values(columns: list[str], token: str) -> dict[str, list[str]]:
    """Fetch distinct values for a list of columns using the caller's OAuth token.

    Used to enrich the agent system prompt with real values so the model writes
    correct WHERE clause literals.  Always called with the user token — never
    with server-level ADC credentials.

    Returns {column: [value, ...]} for columns with ≤ 60 distinct values.
    High-cardinality columns (names, IDs) are omitted.
    """
    if not columns or not token:
        return {}
    ref = TABLE_REFS[0] if TABLE_REFS else ""
    if not ref:
        return {}

    structs = ", ".join(
        f"STRUCT('{c}' AS c, CAST(`{c}` AS STRING) AS v)"
        for c in columns
    )
    # STRING_AGG without DISTINCT: we deduplicate via SELECT DISTINCT in the subquery.
    # HAVING COUNT(*) <= 60 filters out high-cardinality (free-text / ID) columns.
    sample_sql = (
        f"SELECT col, STRING_AGG(v, '|||' ORDER BY v LIMIT 25) AS vals "
        f"FROM (SELECT DISTINCT t.c AS col, t.v AS v "
        f"FROM `{ref}`, UNNEST([{structs}]) AS t "
        f"WHERE t.v IS NOT NULL AND TRIM(t.v) NOT IN ('', '0')) "
        f"GROUP BY col HAVING COUNT(*) <= 60"
    )
    try:
        rows = run_query(sample_sql, token)
        return {
            row["col"]: [v.strip() for v in str(row["vals"]).split("|||") if v.strip()]
            for row in rows if row.get("vals")
        }
    except Exception as exc:
        logger.warning(f"fetch_column_sample_values failed: {exc}")
        return {}

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
            SUM(ytd_spend) AS spend_to_date,
            SUM(ytd_spend) AS commit_spend,
            SAFE_DIVIDE(SUM(ytd_spend), NULLIF(SUM(SAFE_CAST(budget AS FLOAT64)), 0)) * 100 AS pct_spend
        FROM {TABLE_REF}
    """,

    "monthly_capital_expense": f"""
        SELECT month, project_class, SUM(Dollars) AS Dollars
        FROM (
            SELECT month, m_ord, {_PC_LABEL} AS project_class, Dollars
            FROM (
                SELECT 'Jan' AS month, 1 AS m_ord, project_class, period_01dollars AS Dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Feb',2, project_class, period_02dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Mar',3, project_class, period_03dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Apr',4, project_class, period_04dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'May',5, project_class, period_05dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Jun',6, project_class, period_06dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Jul',7, project_class, period_07dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Aug',8, project_class, period_08dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Sep',9, project_class, period_09dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Oct',10, project_class, period_10dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Nov',11, project_class, period_11dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
                UNION ALL SELECT 'Dec',12, project_class, period_12dollars FROM {TABLE_REF} WHERE {_PC_FILTER}
            )
        )
        GROUP BY month, project_class ORDER BY MIN(m_ord)
    """,

    "monthly_fte": f"""
        SELECT month, SUM(FTP) AS FTP, SUM(Dollars) AS Dollars
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord, period_01ftp AS FTP, period_01dollars AS Dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,period_02ftp,period_02dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,period_03ftp,period_03dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,period_04ftp,period_04dollars FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,period_05ftp,period_05dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,period_06ftp,period_06dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,period_07ftp,period_07dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,period_08ftp,period_08dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,period_09ftp,period_09dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,period_10ftp,period_10dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,period_11ftp,period_11dollars FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,period_12ftp,period_12dollars FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,

    "hierarchy_table": f"""
        SELECT
            resourcevp AS Hierarchy,
            resource_manager AS Leader,
            COUNT(DISTINCT racfidpo) AS HC,
            ROUND(AVG(fte_average), 1) AS FTE,
            SUM(eff_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Expense_Pct,
            SUM(eff_spend) AS Committed_Spend
        FROM (
            SELECT *,
                COALESCE(NULLIF(ytd_spend,0),
                    COALESCE(period_01dollars,0)+COALESCE(period_02dollars,0)+COALESCE(period_03dollars,0)+
                    COALESCE(period_04dollars,0)+COALESCE(period_05dollars,0)+COALESCE(period_06dollars,0)+
                    COALESCE(period_07dollars,0)+COALESCE(period_08dollars,0)+COALESCE(period_09dollars,0)+
                    COALESCE(period_10dollars,0)+COALESCE(period_11dollars,0)+COALESCE(period_12dollars,0)) AS eff_spend
            FROM {TABLE_REF}
            WHERE resourcevp IS NOT NULL
        )
        GROUP BY resourcevp, resource_manager
        ORDER BY Spend_to_Date DESC
    """,

    "capital_expense_donut": f"""
        SELECT {_PC_LABEL} AS type, SUM(ytd_spend) AS amount
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
            SELECT 'Jan' AS month,1 AS m_ord,project_class,period_01dollars AS Dollars,period_01ftp AS FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,project_class,period_02dollars,period_02ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,project_class,period_03dollars,period_03ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,project_class,period_04dollars,period_04ftp FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,project_class,period_05dollars,period_05ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,project_class,period_06dollars,period_06ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,project_class,period_07dollars,period_07ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,project_class,period_08dollars,period_08ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,project_class,period_09dollars,period_09ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,project_class,period_10dollars,period_10ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,project_class,period_11dollars,period_11ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,project_class,period_12dollars,period_12ftp FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,
}

VENDOR_SCORECARD_QUERIES = {
    "vendor_table": f"""
        SELECT
            vendor,
            ROUND(SUM(period_01ftp+period_02ftp+period_03ftp+period_04ftp+period_05ftp+period_06ftp+period_07ftp+period_08ftp+period_09ftp+period_10ftp+period_11ftp+period_12ftp), 1) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            SUM(ytd_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='TM' THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100, 2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='Fixed Fee' THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100, 2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100, 2) AS Expense_Pct,
            SUM(ytd_spend) AS Committed_Spend
        FROM {TABLE_REF}
        WHERE vendor IS NOT NULL AND vendor != ''
        GROUP BY vendor
        ORDER BY Spend_to_Date DESC
    """,

    "offshore_onshore_bar": f"""
        SELECT fob, ROUND(SUM(fte_average),1) AS FTE
        FROM {TABLE_REF}
        WHERE fob IS NOT NULL AND TRIM(fob) NOT IN ('', '0')
        GROUP BY fob
        ORDER BY FTE DESC
        LIMIT 10
    """,

    "billtype_bar": f"""
        SELECT billtype, SUM(ytd_spend) AS Spend
        FROM {TABLE_REF}
        WHERE billtype IN ('TM','Fixed Fee')
        GROUP BY billtype
    """,

    "monthly_vendor_spend": f"""
        SELECT month, billtype, SUM(Dollars) AS Dollars
        FROM (
            SELECT 'Jan' AS month,1 AS m_ord, billtype, period_01dollars AS Dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Feb',2,billtype,period_02dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Mar',3,billtype,period_03dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Apr',4,billtype,period_04dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'May',5,billtype,period_05dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Jun',6,billtype,period_06dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Jul',7,billtype,period_07dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Aug',8,billtype,period_08dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Sep',9,billtype,period_09dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Oct',10,billtype,period_10dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Nov',11,billtype,period_11dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
            UNION ALL SELECT 'Dec',12,billtype,period_12dollars FROM {TABLE_REF} WHERE billtype IN ('TM','Fixed Fee')
        )
        GROUP BY month, billtype ORDER BY MIN(m_ord)
    """,

    "spend_by_tier_monthly": f"""
        SELECT month, resource_category, Dollars
        FROM (
            SELECT month, resource_category, SUM(Dollars) AS Dollars, MIN(m_ord) AS _sort
            FROM (
                SELECT 'Jan' AS month,1 AS m_ord,resource_category,period_01dollars AS Dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Feb',2,resource_category,period_02dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Mar',3,resource_category,period_03dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Apr',4,resource_category,period_04dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'May',5,resource_category,period_05dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Jun',6,resource_category,period_06dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Jul',7,resource_category,period_07dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Aug',8,resource_category,period_08dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Sep',9,resource_category,period_09dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Oct',10,resource_category,period_10dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Nov',11,resource_category,period_11dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Dec',12,resource_category,period_12dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
            )
            GROUP BY month, resource_category
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
            SELECT 'Jan' AS month,1 AS m_ord,project_class,period_01dollars AS Dollars,period_01ftp AS FTP FROM {TABLE_REF}
            UNION ALL SELECT 'Feb',2,project_class,period_02dollars,period_02ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Mar',3,project_class,period_03dollars,period_03ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Apr',4,project_class,period_04dollars,period_04ftp FROM {TABLE_REF}
            UNION ALL SELECT 'May',5,project_class,period_05dollars,period_05ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Jun',6,project_class,period_06dollars,period_06ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Jul',7,project_class,period_07dollars,period_07ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Aug',8,project_class,period_08dollars,period_08ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Sep',9,project_class,period_09dollars,period_09ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Oct',10,project_class,period_10dollars,period_10ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Nov',11,project_class,period_11dollars,period_11ftp FROM {TABLE_REF}
            UNION ALL SELECT 'Dec',12,project_class,period_12dollars,period_12ftp FROM {TABLE_REF}
        )
        GROUP BY month ORDER BY MIN(m_ord)
    """,

    "vendor_kpis": f"""
        SELECT
            COUNT(DISTINCT vendor)   AS Total_Vendors,
            COUNT(DISTINCT racfidpo) AS Total_Resources,
            SUM(ytd_spend)           AS Total_Cost
        FROM {TABLE_REF}
        WHERE vendor IS NOT NULL
          AND LOWER(TRIM(vendor)) != 'internal'
    """,

    "vendor_resource_count": f"""
        SELECT vendor, COUNT(DISTINCT racfidpo) AS Resource_Count
        FROM {TABLE_REF}
        WHERE vendor IS NOT NULL
          AND LOWER(TRIM(vendor)) != 'internal'
        GROUP BY vendor
        ORDER BY Resource_Count DESC
        LIMIT 15
    """,

    "tier_breakdown": f"""
        SELECT
            resource_category AS Tier,
            COUNT(DISTINCT racfidpo) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='Fixed Fee' THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100,1) AS FixedFee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='TM' THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100,1) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100,1) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN ytd_spend ELSE 0 END), NULLIF(SUM(ytd_spend),0))*100,1) AS Expense_Pct,
            SUM(ytd_spend) AS Spend_to_Date
        FROM {TABLE_REF}
        WHERE resource_category IS NOT NULL
        GROUP BY resource_category
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
            resourcevp,
            vendor,
            resource_manager AS Leader,
            COUNT(DISTINCT racfidpo) AS FTP,
            0 AS Offshore_Pct,
            0 AS Onshore_Pct,
            SUM(eff_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='TM' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN billtype='Fixed Fee' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_CAPITAL} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN {_PC_IS_EXPENSE} THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Expense_Pct
        FROM (
            SELECT *,
                COALESCE(NULLIF(ytd_spend,0),
                    COALESCE(period_01dollars,0)+COALESCE(period_02dollars,0)+COALESCE(period_03dollars,0)+
                    COALESCE(period_04dollars,0)+COALESCE(period_05dollars,0)+COALESCE(period_06dollars,0)+
                    COALESCE(period_07dollars,0)+COALESCE(period_08dollars,0)+COALESCE(period_09dollars,0)+
                    COALESCE(period_10dollars,0)+COALESCE(period_11dollars,0)+COALESCE(period_12dollars,0)) AS eff_spend
            FROM {TABLE_REF}
            WHERE resourcevp IS NOT NULL
        )
        GROUP BY resourcevp, vendor, resource_manager
        ORDER BY resourcevp, Spend_to_Date DESC
    """,

    "spend_by_tier_monthly": f"""
        SELECT month, resource_category, Dollars
        FROM (
            SELECT month, resource_category, SUM(Dollars) AS Dollars, MIN(m_ord) AS _sort
            FROM (
                SELECT 'Jan' AS month,1 AS m_ord,resource_category,period_01dollars AS Dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Feb',2,resource_category,period_02dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Mar',3,resource_category,period_03dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Apr',4,resource_category,period_04dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'May',5,resource_category,period_05dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Jun',6,resource_category,period_06dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Jul',7,resource_category,period_07dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Aug',8,resource_category,period_08dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Sep',9,resource_category,period_09dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Oct',10,resource_category,period_10dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Nov',11,resource_category,period_11dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
                UNION ALL SELECT 'Dec',12,resource_category,period_12dollars FROM {TABLE_REF} WHERE resource_category IS NOT NULL
            )
            GROUP BY month, resource_category
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
