"""Seed default glossary terms and favorite queries into the database."""
from database import SessionLocal
from models import GlossaryTerm, Favorite

DEFAULT_GLOSSARY = [
    ("FTP", "Full-Time Placement — headcount expressed as a decimal (1.0 = one full-time resource)", "Period_01_FTP = 0.5 means half-time for that period"),
    ("FTE", "Full-Time Equivalent — the average FTE count over a period", "FTE_AVERAGE = 147 means the team averaged 147 full-time equivalents"),
    ("TM", "Time & Materials — a billing model where hours worked are invoiced at an agreed rate", "BillType = 'TM'"),
    ("Fixed Fee", "Fixed-price contract — a set dollar amount regardless of hours consumed", "BillType = 'Fixed Fee'"),
    ("Capital", "Capitalized spend — investment classified as a long-term asset (e.g., software development)", "Project_Class = 'Capital'"),
    ("Expense", "Operating expense — costs expensed in the current period", "Project_Class = 'Expense'"),
    ("Onshore", "Resources physically located domestically (within the US)", "FOB = 'Onshore'"),
    ("Offshore", "Resources physically located internationally", "FOB = 'Offshore'"),
    ("YTD", "Year-to-Date — cumulative total from the start of the fiscal year through the current period", "YTD_Spend = sum of Period_01 through current period"),
    ("HC", "Headcount — the count of distinct resources active in a period", "COUNT(DISTINCT RACFID_PO)"),
    ("vs LM", "Versus Last Month — the change from the prior month's value", "FTE vs LM = current FTE minus prior month FTE"),
    ("Committed Spend", "Total budget committed, typically equal to YTD Spend when 100% spent", "Committed_Spend ≈ YTD_Spend at period close"),
    ("Hierarchy", "Organizational reporting structure from VP down to Resource Manager", "ResourceVP → Resource_Manager → Resource"),
    ("ResourceVP", "Vice President responsible for the resource group", "ResourceVP column"),
    ("Intake", "A formal work request submitted for planning and budgeting", "Work_InTake_Id, Intake_Category, Intake_Status"),
    ("Portfolio", "A grouping of related projects managed under a common owner", "Portfolio_Intake, Heirarchy_Portfolio"),
    ("LOA", "Leave of Absence — planned or unplanned time away from work", "LOA_Start, LOA_End, LOA_Status"),
    ("CIP", "Construction in Progress — capital projects not yet placed in service", "CIP_to_Close column"),
    ("APO", "Asset Product Owner — the accountable owner of a capitalized asset", "APO_Classification, BB_APO"),
    ("Benefits", "Employer-paid benefits costs added on top of base salary/rate", "Line_Item_Benefits, Period_XX_W_Ben_and_Cap_Serve"),
    ("Cap Serve", "Capitalization service fee — overhead allocated to capital projects", "Line_Item_Cap_Serve"),
    ("R_G_T", "Red / Green / Trending — traffic-light status indicator for a resource or project", "R_G_T column: R=Red, G=Green, T=Trending"),
    ("MMAT", "Macro Master Assignment Tracking — internal task tracking system", "MMAT_Task_ID, MMAT_Category"),
    ("Tier", "Vendor tier classification (Tier 1 = strategic, Tier 4 = niche/specialty)", "Used in Vendor Summary scorecard"),
    ("Period", "Fiscal month (Period_01 = January, Period_12 = December)", "Period_01_Dollars through Period_12_Dollars"),
]

DEFAULT_FAVORITES = [
    (
        "Total YTD Spend by Resource Manager",
        "Show total year-to-date spend by resource manager",
        "SELECT Resource_Manager, SUM(YTD_Spend) AS Total_YTD_Spend, COUNT(DISTINCT RACFID_PO) AS HC, ROUND(AVG(FTE_AVERAGE),1) AS Avg_FTE FROM `mygclearning.test.one` WHERE Resource_Manager IS NOT NULL GROUP BY Resource_Manager ORDER BY Total_YTD_Spend DESC LIMIT 20",
        "bar",
    ),
    (
        "Capital vs Expense YTD Split",
        "Show capital versus expense spend breakdown for YTD",
        "SELECT Project_Class, SUM(YTD_Spend) AS Total_Spend FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class",
        "donut",
    ),
    (
        "Monthly Spend Trend by Project Class",
        "Show monthly dollar spend trend split by capital and expense",
        "SELECT 'Jan' AS Month, Project_Class, SUM(Period_01_Dollars) AS Spend FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Feb', Project_Class, SUM(Period_02_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Mar', Project_Class, SUM(Period_03_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Apr', Project_Class, SUM(Period_04_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'May', Project_Class, SUM(Period_05_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Jun', Project_Class, SUM(Period_06_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Jul', Project_Class, SUM(Period_07_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Aug', Project_Class, SUM(Period_08_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Sep', Project_Class, SUM(Period_09_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Oct', Project_Class, SUM(Period_10_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Nov', Project_Class, SUM(Period_11_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class UNION ALL SELECT 'Dec', Project_Class, SUM(Period_12_Dollars) FROM `mygclearning.test.one` WHERE Project_Class IN ('Capital','Expense') GROUP BY Project_Class ORDER BY Month",
        "stacked_bar",
    ),
    (
        "Top 10 Vendors by YTD Spend",
        "Show top 10 vendors ranked by year-to-date spend",
        "SELECT Vendor, SUM(YTD_Spend) AS Total_Spend, ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Capital' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Capital_Pct, ROUND(SAFE_DIVIDE(SUM(CASE WHEN Project_Class='Expense' THEN YTD_Spend ELSE 0 END), NULLIF(SUM(YTD_Spend),0))*100,1) AS Expense_Pct FROM `mygclearning.test.one` WHERE Vendor IS NOT NULL AND Vendor != '' GROUP BY Vendor ORDER BY Total_Spend DESC LIMIT 10",
        "bar",
    ),
    (
        "FTE Average by Business Area",
        "Show average FTE headcount per business area",
        "SELECT BusinessArea, ROUND(AVG(FTE_AVERAGE),2) AS Avg_FTE, COUNT(DISTINCT RACFID_PO) AS HC FROM `mygclearning.test.one` WHERE BusinessArea IS NOT NULL GROUP BY BusinessArea ORDER BY Avg_FTE DESC",
        "horizontal_bar",
    ),
    (
        "TM vs Fixed Fee Spend by Vendor",
        "Compare time-and-materials versus fixed-fee spend across vendors",
        "SELECT Vendor, SUM(CASE WHEN BillType='TM' THEN YTD_Spend ELSE 0 END) AS TM_Spend, SUM(CASE WHEN BillType='Fixed Fee' THEN YTD_Spend ELSE 0 END) AS Fixed_Fee_Spend FROM `mygclearning.test.one` WHERE Vendor IS NOT NULL AND Vendor != '' GROUP BY Vendor ORDER BY (TM_Spend + Fixed_Fee_Spend) DESC LIMIT 15",
        "stacked_bar",
    ),
]


def seed():
    db = SessionLocal()
    try:
        if db.query(GlossaryTerm).filter_by(is_default=True).count() == 0:
            for term, definition, example in DEFAULT_GLOSSARY:
                db.add(GlossaryTerm(term=term, definition=definition, example=example, is_default=True))

        if db.query(Favorite).filter_by(is_default=True).count() == 0:
            for name, nl_query, sql_query, chart_type in DEFAULT_FAVORITES:
                db.add(Favorite(name=name, nl_query=nl_query, sql_query=sql_query, chart_type=chart_type, is_default=True))

        db.commit()
    finally:
        db.close()
