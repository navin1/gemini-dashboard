import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
_model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

_TABLE_REF = "`mygclearning.test.one`"

SCHEMA_CONTEXT = """
BigQuery table: `mygclearning.test.one`

Key columns (grouped by category):

RESOURCE / PERSON:
  Resource_SOW_Name STRING  - Resource full name per SOW
  RACFID_PO STRING          - Unique resource identifier
  First_Name, Last_Name STRING
  Resource_Type STRING      - 'FTE', 'Contractor', etc.
  Status STRING             - Active/inactive status
  Resource_Manager STRING   - Direct manager
  ResourceVP STRING         - VP over the resource
  FTE_AVERAGE FLOAT64       - Average FTE headcount
  R_G_T STRING              - Red/Green/Trending status indicator
  LOA_Start, LOA_End STRING - Leave of Absence dates
  LOA_Status STRING

VENDOR / CONTRACT:
  Vendor STRING             - Vendor company name
  BillType STRING           - 'TM' (Time & Materials) or 'Fixed Fee'
  FOB STRING                - 'Onshore' or 'Offshore'
  Role_SOW_Name STRING      - Role title per SOW
  Rate STRING               - Billing rate
  TM_Contractor__PO STRING  - PO number for TM contractors
  Fixed_Fee_Gross_Account FLOAT64

PROJECT / INTAKE:
  PRJ STRING                - Project ID
  ProjectName STRING
  Project_Class STRING      - 'Capital' or 'Expense'
  Project_Status STRING
  BusinessArea STRING
  Business_Team STRING
  BusinessFunction FLOAT64
  Project_PGM STRING
  BUDGET_OWNER STRING
  Project_TECH_VP STRING
  Project_TECH_SENIOR_DIRECTOR STRING
  Work_InTake_Id STRING
  Intake_Category STRING
  Intake_Status STRING
  Intake_Priority_Type STRING
  Portfolio_Intake STRING
  Heirarchy_Portfolio FLOAT64
  Heirarchy_Tech_or_NonTech STRING
  TabName STRING            - Sheet/tab identifier for the data source
  Current_Period STRING     - Current fiscal period label

FINANCIAL (period = fiscal month, Period_01=Jan, Period_12=Dec):
  YTD_Spend FLOAT64                              - Year-to-date total spend
  Amount FLOAT64                                 - Line item amount
  Period_01_Dollars .. Period_12_Dollars FLOAT64 - Monthly dollar spend
  Period_01_FTP .. Period_12_FTP FLOAT64         - Monthly FTP (headcount decimal)
  Period_01_Hours .. Period_12_Hours FLOAT64     - Monthly hours
  Period_01_W_Ben_and_Cap_Serve .. Period_12_W_Ben_and_Cap_Serve FLOAT64 - Monthly spend with benefits + cap serve
  Line_Item_Benefits FLOAT64
  Line_Item_Cap_Serve FLOAT64
  Line_Item_Total_w__Benefits___Cap_Serve FLOAT64
  Fixed_Fee_Gross_Account FLOAT64
  Current_Year_Intake_Budget STRING
  Intake_Budget_2027, Intake_Budget_2028, Intake_Budget_2029 FLOAT64
  APO_Classification STRING
  CIP_to_Close FLOAT64
"""

_SYSTEM_PROMPT = f"""You are an expert data analyst for a workforce and spend management dashboard. Generate BigQuery SQL from natural language requests.

{SCHEMA_CONTEXT}

RULES:
1. Always use the full table reference: `mygclearning.test.one`
2. Use SAFE_DIVIDE(a, b) instead of a/b to avoid zero-division errors
3. Use NULLIF(col, 0) where appropriate
4. Limit results to 50 rows unless the user asks for more
5. For time-series across periods, UNION ALL each period into (month_label, category, value) rows
6. Return only valid BigQuery Standard SQL (no semicolons at end)
7. Dollar values are FLOAT64 — the UI formats them; do not cast to STRING

Respond ONLY with a raw JSON object (no markdown fences, no explanation):
{{
  "sql": "SELECT ...",
  "chart_type": "bar|stacked_bar|line|combo|donut|pie|table|kpi|horizontal_bar",
  "title": "Short widget title",
  "x_axis": "column_name_or_null",
  "y_axis": ["column_name"],
  "color_field": "column_name_or_null",
  "stacked": false,
  "dual_axis": false,
  "secondary_y": "column_name_or_null",
  "ai_description": "2-3 sentence insight explaining what this chart shows and why it matters for workforce/spend management."
}}

Chart type guide:
  bar           - grouped bars comparing categories
  stacked_bar   - stacked bars for part-of-whole (e.g. Capital+Expense per month)
  line          - trend over time
  combo         - bar + line on same chart (e.g. spend bars + FTE line)
  donut         - 2-4 segment proportion (e.g. Capital vs Expense YTD)
  pie           - proportional segments
  table         - detailed tabular data (best for >5 columns)
  kpi           - one or more summary metrics (e.g. total spend, headcount, %). Use when user asks for a number/stat/metric rather than a trend or comparison. The SQL should return a single row with named columns — each column becomes one KPI card.
  horizontal_bar- ranked list (best for vendor/manager comparisons)
"""


def generate_widget(nl_query: str, glossary_terms: list[dict] | None = None) -> dict:
    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']} → {t['definition']}" for t in glossary_terms)
        glossary_ctx = (
            f"\n\nUser-defined aliases (substitute these when interpreting the request — "
            f"treat each term as its mapped value in all contexts including table names, "
            f"column aliases, and descriptions):\n{lines}"
        )

    prompt = f"{_SYSTEM_PROMPT}{glossary_ctx}\n\nUser request: {nl_query}"

    response = _model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


_CHAT_SYSTEM = f"""You are an AI analyst for a workforce and spend management dashboard. You have access to BigQuery and can answer questions, explain data, and generate charts.

{SCHEMA_CONTEXT}

BigQuery rules (when generating SQL):
- Always use `mygclearning.test.one`
- Use SAFE_DIVIDE(a, b) for division; NULLIF(col, 0) where needed
- Limit to 50 rows unless asked otherwise
- For period time-series: UNION ALL each period into (month_label, category, value) rows
- Valid BigQuery Standard SQL only (no trailing semicolons)

You MUST respond with a single raw JSON object — no markdown, no prose outside JSON:
{{
  "text": "Your conversational reply. Explain what you found, answer the question, or confirm what chart you created. 2-5 sentences.",
  "intent": "explain | chart | both",
  "widget": {{
    "sql": "SELECT ...",
    "chart_type": "bar|stacked_bar|line|combo|donut|pie|table|kpi|horizontal_bar",
    "title": "Short chart title",
    "x_axis": "column_name_or_null",
    "y_axis": ["column_name"],
    "color_field": "column_name_or_null",
    "stacked": false,
    "dual_axis": false,
    "secondary_y": "column_name_or_null",
    "ai_description": "1-2 sentence insight for the chart."
  }},
  "suggested_questions": ["Short follow-up question 1?", "Short follow-up question 2?", "Short follow-up question 3?"]
}}

Rules:
- Set intent="explain" when the user asks a question, wants a definition, or asks you to describe data — no widget needed.
- Set intent="chart" when the user asks to visualize, show, create, or display data — always include widget.
- Set intent="both" when both a textual explanation AND a chart are valuable.
- When intent is "explain", omit the widget field entirely.
- Always maintain context from the conversation history — "what about last month?" refers to the previous query.
- If you cannot answer (e.g., column doesn't exist), explain why in the text field and set intent="explain".
- Always include exactly 2-3 suggested_questions: short, specific follow-up questions a user might naturally ask next, grounded in the current answer and dataset context.
"""


def chat_turn(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
) -> dict:
    """
    Multi-turn conversational query. history is a list of
    {"role": "user"|"assistant", "content": "..."} dicts.
    Returns {"text": ..., "intent": ..., "widget": {...} | None}
    """
    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']} → {t['definition']}" for t in glossary_terms)
        glossary_ctx = (
            f"\n\nUser-defined aliases (apply these as substitutions when interpreting "
            f"the user's message — treat each term as its mapped value in all contexts: "
            f"table names, column names, abbreviations, and natural language references. "
            f"For example, if 'src' → '`mygclearning.test.one`', then "
            f"'SELECT * FROM src' means 'SELECT * FROM `mygclearning.test.one`'):\n{lines}"
        )

    # Build Gemini multi-turn history
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    chat = _model.start_chat(history=gemini_history)
    prompt = f"{_CHAT_SYSTEM}{glossary_ctx}\n\nUser: {message}"
    response = chat.send_message(prompt)

    raw = response.text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]

    result = json.loads(raw.strip())
    return result


def refine_widget(current_sql: str, nl_modification: str, glossary_terms: list[dict] | None = None) -> dict:
    """Modify an existing widget's SQL based on a natural language instruction."""
    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']}: {t['definition']}" for t in glossary_terms)
        glossary_ctx = f"\n\nDomain glossary:\n{lines}"

    prompt = (
        f"{_SYSTEM_PROMPT}{glossary_ctx}\n\n"
        f"Existing SQL query:\n```sql\n{current_sql}\n```\n\n"
        f"User wants to change it: {nl_modification}\n\n"
        f"Return a full updated widget JSON. Preserve chart_type and axis config unless "
        f"the modification clearly requires different visualisation settings."
    )

    response = _model.generate_content(prompt)
    raw = response.text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def generate_pdf_description(title: str, chart_type: str, data_summary: str) -> str:
    prompt = (
        f"You are writing a brief narrative for a PDF report section.\n"
        f"Widget title: {title}\nChart type: {chart_type}\nData summary: {data_summary}\n\n"
        f"Write 2-4 sentences of professional, human-readable insight about this data. "
        f"Focus on what the numbers mean for workforce or spend management. "
        f"Do not mention chart types or technical terms. Plain text only."
    )
    response = _model.generate_content(prompt)
    return response.text.strip()
