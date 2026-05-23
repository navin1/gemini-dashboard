import os
from google.cloud import bigquery
from auth import get_bq_credentials
from dotenv import load_dotenv

load_dotenv()

# Project where the data lives (used in table references only)
PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID") or "mygclearning"
DATASET    = os.getenv("BIGQUERY_DATASET")    or "test"
TABLE      = os.getenv("BIGQUERY_TABLE")      or "one"
TABLE_REF  = f"`{PROJECT_ID}.{DATASET}.{TABLE}`"

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
            SELECT 'Jan' AS month, 1 AS m_ord, Project_Class, Period_01_Dollars AS Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Feb',2, Project_Class, Period_02_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Mar',3, Project_Class, Period_03_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Apr',4, Project_Class, Period_04_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'May',5, Project_Class, Period_05_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Jun',6, Project_Class, Period_06_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Jul',7, Project_Class, Period_07_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Aug',8, Project_Class, Period_08_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Sep',9, Project_Class, Period_09_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Oct',10, Project_Class, Period_10_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Nov',11, Project_Class, Period_11_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
            UNION ALL SELECT 'Dec',12, Project_Class, Period_12_Dollars FROM {TABLE_REF} WHERE Project_Class IN ('Capital','Expense')
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
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Capital' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Expense' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100, 2) AS Expense_Pct,
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
        SELECT Project_Class AS type, SUM(YTD_Spend) AS amount
        FROM {TABLE_REF}
        WHERE Project_Class IN ('Capital','Expense')
        GROUP BY Project_Class
    """,

    "monthly_cap_exp_ftp": f"""
        SELECT month,
            SUM(CASE WHEN Project_Class='Capital' THEN Dollars ELSE 0 END) AS Capital,
            SUM(CASE WHEN Project_Class='Expense' THEN Dollars ELSE 0 END) AS Expense,
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
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Offshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100, 1) AS Offshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Onshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100, 1) AS Onshore_Pct,
            SUM(YTD_Spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Capital' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Expense' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100, 2) AS Expense_Pct,
            SUM(YTD_Spend) AS Committed_Spend
        FROM {TABLE_REF}
        WHERE Vendor IS NOT NULL AND Vendor != ''
        GROUP BY Vendor
        ORDER BY Spend_to_Date DESC
    """,

    "offshore_onshore_bar": f"""
        SELECT FOB, ROUND(SUM(FTE_AVERAGE),1) AS FTE
        FROM {TABLE_REF}
        WHERE FOB IN ('Offshore','Onshore')
        GROUP BY FOB
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
            SUM(CASE WHEN Project_Class='Capital' THEN Dollars ELSE 0 END) AS Capital,
            SUM(CASE WHEN Project_Class='Expense' THEN Dollars ELSE 0 END) AS Expense,
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
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Offshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100,1) AS Offshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Onshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100,1) AS Onshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS FixedFee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Capital' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Expense' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Expense_Pct,
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
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Offshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100,1) AS Offshore_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN FOB='Onshore' THEN FTE_AVERAGE ELSE 0 END), NULLIF(SUM(FTE_AVERAGE),0))*100,1) AS Onshore_Pct,
            SUM(eff_spend) AS Spend_to_Date,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='TM' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS TM_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN BillType='Fixed Fee' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Fixed_Fee_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Capital' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Capital_Pct,
            ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Expense' THEN eff_spend ELSE 0 END), NULLIF(SUM(eff_spend),0))*100,2) AS Expense_Pct
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
