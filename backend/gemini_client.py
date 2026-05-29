import os
import re
import json
import time
import logging

import google.auth
import google.auth.transport.requests
import asyncio
from concurrent.futures import ThreadPoolExecutor
import vertexai
from vertexai.generative_models import GenerativeModel, Content, Part, Tool, FunctionDeclaration

import bigquery_client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Credential resolution ──────────────────────────────────────────────────────
# Priority: user ADC (gcloud auth application-default login) → SA JSON fallback.
# BigQuery always use user ADC only — SA fallback is Vertex AI only.

def _get_vertex_credentials():
    auth_req = google.auth.transport.requests.Request()

    # 1. User's own ADC credentials
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(auth_req)
        logger.info("Vertex AI: using user ADC credentials")
        return creds
    except Exception as e:
        logger.debug(f"Vertex AI: user ADC failed ({type(e).__name__}: {e}), trying SA fallback…")

    # 2. Service-account JSON fallback (Vertex AI only — does not apply to BQ)
    sa_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if sa_file and os.path.exists(sa_file):
        try:
            creds, _ = google.auth.load_credentials_from_file(
                sa_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            logger.info("Vertex AI: using service-account fallback credentials")
            return creds
        except Exception as e:
            logger.warning(f"Vertex AI: SA fallback failed ({type(e).__name__}: {e})")

    raise RuntimeError(
        "No Vertex AI credentials available. "
        "Run: gcloud auth application-default login  "
        "or set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON with roles/aiplatform.user"
    )


# ── Vertex AI initialisation ───────────────────────────────────────────────────

def _init_vertex():
    project  = os.getenv("VERTEX_AI_PROJECT", "")
    location = os.getenv("VERTEX_AI_LOCATION", "us-central1")
    if not project:
        raise RuntimeError(
            "VERTEX_AI_PROJECT is not set in .env. "
            "Set it to the GCP project where Vertex AI is enabled."
        )
    creds = _get_vertex_credentials()
    vertexai.init(project=project, location=location, credentials=creds)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    logger.info(f"Vertex AI initialised: project={project} location={location} model={model_name}")
    return GenerativeModel(model_name)


try:
    _model = _init_vertex()
except Exception as exc:
    logger.error(f"Vertex AI init failed: {exc}")
    _model = None  # routes will raise a clean 503 when _model is None


# ── Schema helpers ─────────────────────────────────────────────────────────────

_FALLBACK_SCHEMA = """BigQuery table: `mygclearning.test.one`

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
  CIP_to_Close FLOAT64"""

_schema_cache: str | None = None


def _get_schema() -> str:
    global _schema_cache, _AGENT_MODEL_INSTANCE
    if _schema_cache is None:
        prev = _schema_cache
        try:
            _schema_cache = bigquery_client.build_schema_context()
        except Exception:
            _schema_cache = _FALLBACK_SCHEMA
        # If the schema changed (e.g. first real fetch after fallback), force
        # the cached agent model to rebuild so it gets the enriched schema.
        if _schema_cache != prev:
            _AGENT_MODEL_INSTANCE = None
    return _schema_cache


def _table_refs_clause() -> str:
    refs = [f"`{r}`" for r in bigquery_client.TABLE_REFS]
    if len(refs) == 1:
        return refs[0]
    return ", ".join(refs[:-1]) + f" and {refs[-1]}"


def _build_system_prompt() -> str:
    schema = _get_schema()
    tables_clause = _table_refs_clause()
    return f"""You are an expert data analyst for a workforce and spend management dashboard. Generate BigQuery SQL from natural language requests.

{schema}

RULES:
1. Only query the tables listed above. Never reference tables not shown in the schema.
2. Use the exact full table reference(s): {tables_clause}
3. Use SAFE_DIVIDE(a, b) instead of a/b to avoid zero-division errors
4. Use NULLIF(col, 0) where appropriate
5. Limit results to 50 rows unless the user asks for more
6. For time-series across periods, UNION ALL each period into (month_label, category, value) rows
7. Return only valid BigQuery Standard SQL (no semicolons at end)
8. Dollar values are FLOAT64 — the UI formats them; do not cast to STRING

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
  bar           - DEFAULT for any category vs number query. Vertical bars, X=category (string), Y=number.
  stacked_bar   - stacked bars for part-of-whole (e.g. Capital+Expense per month)
  line          - trend over time
  combo         - bar + line on same chart (e.g. spend bars + FTE line)
  donut         - 2-4 segment proportion (e.g. Capital vs Expense YTD)
  pie           - proportional segments
  table         - detailed tabular data (best for >5 columns)
  kpi           - one or more summary metrics (e.g. total spend, headcount, %). Use when user asks for a number/stat/metric rather than a trend or comparison. The SQL should return a single row with named columns — each column becomes one KPI card.
  horizontal_bar- ranked list (best for vendor/manager comparisons)

x_axis / y_axis rules (CRITICAL):
  - x_axis MUST be the categorical/string column (vendor name, project, month label, resource type, etc.)
  - y_axis MUST be the numeric/measure column(s) (spend, count, FTE, amount, etc.)
  - NEVER assign a numeric column to x_axis for bar, stacked_bar, line, or combo charts
  - When the result has exactly 1 string column and 1 numeric column, always use bar chart with x_axis=string column, y_axis=[numeric column]
"""


def _build_chat_system() -> str:
    schema = _get_schema()
    tables_clause = _table_refs_clause()
    return f"""You are an AI analyst for a workforce and spend management dashboard. You have access to BigQuery and can answer questions, explain data, and generate charts.

{schema}

BigQuery rules (when generating SQL):
- Only query the tables listed above. Never reference tables not shown in the schema.
- Use exact full table reference(s): {tables_clause}
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
- x_axis MUST be the categorical/string column. y_axis MUST be the numeric column(s). NEVER put a numeric column in x_axis for bar/line/combo charts. Default chart type for 1 string + 1 number column is "bar".
"""


# ── Response parsing ───────────────────────────────────────────────────────────

def _response_text(response) -> str:
    """Safely extract text from a Vertex AI response.

    response.text raises ValueError when the candidate contains only
    function-call parts and no text part. Guard against that and also
    against None so callers always receive a plain str.
    """
    try:
        return (response.text or "").strip()
    except (ValueError, AttributeError):
        return ""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        raise ValueError("Model returned an empty response")
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    if not raw:
        raise ValueError("Model returned an empty JSON fence")
    return json.loads(raw)


def _safe_parse_agent_response(raw: str) -> dict:
    """Parse JSON response with two fallbacks for malformed model output."""
    try:
        return _parse_json(raw)
    except Exception:
        pass
    # Fallback 1: find the first {...} block anywhere in the text
    m = re.search(r'\{[\s\S]+\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    # Fallback 2: wrap raw text as a plain text response
    return {
        "text": raw.strip() or "I wasn't able to format a response. Please try rephrasing.",
        "intent": "text",
        "suggested_questions": [],
    }


def _require_model():
    if _model is None:
        raise RuntimeError(
            "Vertex AI model is not initialised. "
            "Check VERTEX_AI_PROJECT in .env and ensure credentials are configured."
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_widget(nl_query: str, glossary_terms: list[dict] | None = None) -> dict:
    _require_model()
    glossary_ctx = _build_glossary_ctx(glossary_terms)
    prompt = f"{_build_system_prompt()}{glossary_ctx}\n\nUser request: {nl_query}"
    response = _model.generate_content(prompt)
    return _parse_json(response.text)


def chat_turn(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
) -> dict:
    _require_model()
    glossary_ctx = _build_glossary_ctx(glossary_terms)

    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

    chat = _model.start_chat(history=vertex_history)
    prompt = f"{_build_chat_system()}{glossary_ctx}\n\nUser: {message}"
    response = chat.send_message(prompt)
    return _safe_parse_agent_response(_response_text(response))


def refine_widget(current_sql: str, nl_modification: str, glossary_terms: list[dict] | None = None) -> dict:
    _require_model()
    glossary_ctx = _build_glossary_ctx(glossary_terms)

    prompt = (
        f"{_build_system_prompt()}{glossary_ctx}\n\n"
        f"Existing SQL query:\n```sql\n{current_sql}\n```\n\n"
        f"User wants to change it: {nl_modification}\n\n"
        f"Return a full updated widget JSON. Preserve chart_type and axis config unless "
        f"the modification clearly requires different visualisation settings."
    )
    response = _model.generate_content(prompt)
    return _parse_json(response.text)


_BQ_TOOL = Tool(function_declarations=[
    FunctionDeclaration(
        name="run_bigquery_query",
        description=(
            "Execute a BigQuery SQL query and return the results. "
            "Use this to explore the data, verify column names, answer questions with live data, "
            "or build up complex answers step-by-step."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": (
                        "Valid BigQuery Standard SQL using fully-qualified table names. "
                        "No trailing semicolons. Use SAFE_DIVIDE for division."
                    ),
                }
            },
            "required": ["sql"],
        },
    )
])


def _build_agent_system() -> str:
    schema = _get_schema()
    tables_clause = _table_refs_clause()
    return f"""You are an expert AI analyst for a workforce and spend management dashboard. You have direct access to BigQuery via the run_bigquery_query tool.

{schema}

BigQuery rules (apply to every SQL you write):
- Only query the tables listed above. Never reference tables not shown in the schema.
- Use exact full table reference(s): {tables_clause}
- Use SAFE_DIVIDE(a, b) for division; NULLIF(col, 0) where needed
- Limit to 50 rows unless asked otherwise
- For period time-series: UNION ALL each period into (month_label, category, value) rows
- Valid BigQuery Standard SQL only (no trailing semicolons)

Behaviour:
- Always call run_bigquery_query to fetch real data before answering. Never hallucinate results.
- You may call the tool multiple times in one turn — explore first, then refine, then summarise.
- When the user asks to visualise data, include a widget in your final JSON response.
- Always maintain context from conversation history.
- If a query errors, try an alternative SQL approach (different column names, different filters) before giving up.
- For filter values (Status, Resource_Type, etc.) use run_bigquery_query with SELECT DISTINCT to discover exact values before applying WHERE clauses.

You MUST end every turn with a single raw JSON object (no markdown, no prose outside the JSON):
{{
  "text": "Your conversational reply. Explain what you found, answer the question, or confirm the chart. 2-5 sentences.",
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
  "suggested_questions": ["Follow-up question 1?", "Follow-up question 2?", "Follow-up question 3?"]
}}

Rules:
- intent="explain" → no widget needed (omit the widget field).
- intent="chart" → always include widget with working SQL.
- intent="both" → include both text explanation and widget.
- Always include exactly 2-3 suggested_questions grounded in the data you just found.
- x_axis MUST be the categorical/string column (vendor, project, month, resource type, etc.). y_axis MUST be the numeric/measure column(s). NEVER assign a numeric column to x_axis for bar, stacked_bar, line, or combo charts. Default chart type for 1 string + 1 numeric column is "bar".

--- FEW-SHOT EXAMPLES ---

Example 1 — Single KPI metric:
User: "What is the total YTD spend?"
Thought: The user wants a single summary number. I should query YTD_Spend, return a kpi chart type with one row.
Tool call → SELECT ROUND(SUM(YTD_Spend), 2) AS total_ytd_spend FROM {tables_clause.split(',')[0].strip().strip('`')} (or first table)
Final JSON:
{{
  "text": "Total year-to-date spend across all projects is $142.3M. This reflects all active and inactive resources combined.",
  "intent": "both",
  "widget": {{
    "sql": "SELECT ROUND(SUM(YTD_Spend), 2) AS total_ytd_spend FROM {tables_clause.split(',')[0].strip().strip('`')}",
    "chart_type": "kpi",
    "title": "Total YTD Spend",
    "x_axis": null,
    "y_axis": ["total_ytd_spend"],
    "color_field": null,
    "stacked": false,
    "dual_axis": false,
    "secondary_y": null,
    "ai_description": "Aggregate year-to-date spend across all resources and projects."
  }},
  "suggested_questions": ["Break down YTD spend by vendor?", "How does Capital compare to Expense spend?", "Which project has the highest YTD spend?"]
}}

Example 2 — Stacked bar time-series across fiscal periods:
User: "Show me monthly spend split by Capital vs Expense over the year"
Thought: Monthly trend with category split = stacked_bar. Periods are columns Period_01_Dollars through Period_12_Dollars. I must UNION ALL each period.
Tool call → verify column names and data exists
Final JSON:
{{
  "text": "Here is the monthly spend broken down by Capital and Expense project class. Capital spend peaks mid-year while Expense stays relatively flat.",
  "intent": "chart",
  "widget": {{
    "sql": "SELECT 'Jan' AS month, 'Capital' AS project_class, SUM(Period_01_Dollars) AS spend FROM {tables_clause.split(',')[0].strip().strip('`')} WHERE Project_Class = 'Capital' GROUP BY 1,2 UNION ALL SELECT 'Jan','Expense',SUM(Period_01_Dollars) FROM {tables_clause.split(',')[0].strip().strip('`')} WHERE Project_Class = 'Expense' GROUP BY 1,2 UNION ALL SELECT 'Feb','Capital',SUM(Period_02_Dollars) FROM {tables_clause.split(',')[0].strip().strip('`')} WHERE Project_Class = 'Capital' GROUP BY 1,2 UNION ALL SELECT 'Feb','Expense',SUM(Period_02_Dollars) FROM {tables_clause.split(',')[0].strip().strip('`')} WHERE Project_Class = 'Expense' GROUP BY 1,2",
    "chart_type": "stacked_bar",
    "title": "Monthly Spend: Capital vs Expense",
    "x_axis": "month",
    "y_axis": ["spend"],
    "color_field": "project_class",
    "stacked": true,
    "dual_axis": false,
    "secondary_y": null,
    "ai_description": "Monthly spend split by project classification. Use this to track how capital investment vs operating expense evolves through the fiscal year."
  }},
  "suggested_questions": ["Which vendor drives the most Capital spend?", "Show headcount trend alongside spend?", "Filter to only active projects?"]
}}

Example 3 — Ranked horizontal bar (top N):
User: "Top 10 vendors by spend"
Thought: Ranking comparison = horizontal_bar. Group by Vendor, sum YTD_Spend, order descending, limit 10.
Tool call → run the query to verify column and get real data
Final JSON:
{{
  "text": "Here are the top 10 vendors by year-to-date spend. The top vendor accounts for a significant portion of total contractor spend.",
  "intent": "chart",
  "widget": {{
    "sql": "SELECT Vendor, ROUND(SUM(YTD_Spend), 2) AS total_spend FROM {tables_clause.split(',')[0].strip().strip('`')} WHERE Vendor IS NOT NULL GROUP BY Vendor ORDER BY total_spend DESC LIMIT 10",
    "chart_type": "horizontal_bar",
    "title": "Top 10 Vendors by YTD Spend",
    "x_axis": "total_spend",
    "y_axis": ["total_spend"],
    "color_field": null,
    "stacked": false,
    "dual_axis": false,
    "secondary_y": null,
    "ai_description": "Ranked vendor spend for the current fiscal year. Helps identify concentration risk and largest contractor relationships."
  }},
  "suggested_questions": ["Compare onshore vs offshore for these vendors?", "Which vendor has the most resources?", "Show vendor spend trend by month?"]
}}
--- END EXAMPLES ---
"""


# ── Contextual distinct-value hints ───────────────────────────────────────────
# ── Entity glossary (JSON file) ───────────────────────────────────────────────

import pathlib as _pathlib

_ENTITY_FILE = _pathlib.Path(__file__).parent / "glossary_entities.json"


def _load_entity_glossary() -> list[dict]:
    """Load hidden entity mappings from glossary_entities.json.

    Returns an empty list if the file is missing or malformed so the app
    never hard-fails because of a missing config file.
    """
    try:
        return json.loads(_ENTITY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _build_glossary_ctx(glossary_terms: list[dict] | None) -> str:
    """Build the glossary context string injected into every agent prompt.

    For entries that carry a bq_column + bq_value the agent receives an exact
    SQL filter fragment so it never has to guess the stored value.
    Plain text entries (no bq_value) fall back to the original alias format.
    """
    if not glossary_terms:
        return ""
    lines = []
    for t in glossary_terms:
        bq_col = t.get("bq_column")
        bq_val = t.get("bq_value")
        if bq_col and bq_val:
            fragment = f"{bq_col} = '{bq_val}'"
            if t.get("bq_table"):
                fragment = f"{t['bq_table']}.{fragment}"
            lines.append(
                f"  {t['term']} → {t['definition']} [SQL filter: {fragment}]"
            )
        else:
            lines.append(f"  {t['term']} → {t['definition']}")
    body = "\n".join(lines)
    return (
        f"\n\nUser-defined aliases (treat each term as its mapped value in all "
        f"contexts — table names, column names, abbreviations. When a SQL filter "
        f"is provided, use it exactly as written):\n{body}"
    )


# ── Contextual column hints ───────────────────────────────────────────────────
# Maps keywords the user might say → (column_name, fetch_limit).
# When a keyword appears in the message we pre-fetch distinct values for that
# column so the model can write precise WHERE clauses without an extra tool call.

_KEYWORD_COLUMNS: list[tuple[list[str], str, int]] = [
    (["vendor", "vendors", "supplier"],           "Vendor",               60),
    (["status", "active", "inactive"],            "Status",               30),
    (["resource type", "resource_type", "fte", "contractor"], "Resource_Type", 20),
    (["bill type", "billtype", "t&m", "fixed fee"], "BillType",           10),
    (["onshore", "offshore", "fob"],              "FOB",                  10),
    (["project class", "capital", "expense"],     "Project_Class",        10),
    (["business area", "businessarea"],           "BusinessArea",         40),
    (["intake priority", "priority"],             "Intake_Priority_Type", 15),
    (["intake status"],                           "Intake_Status",        15),
    (["project status"],                          "Project_Status",       15),
    (["tab", "tabname", "sheet"],                 "TabName",              20),
    (["manager", "resource manager"],             "Resource_Manager",     50),
]

# Cache for distinct column values — keyed by column name, 10-minute TTL.
_HINTS_CACHE: dict[str, tuple[float, list[str]]] = {}
_HINTS_TTL = 600

_CONVERSATIONAL_RE = re.compile(
    r'^(?:hi|hello|hey|thanks|thank you|ok|okay|sure|yes|no|got it|great|perfect|👍|🙏)[\s!.?]*$',
    re.IGNORECASE,
)

# Phrases that signal a live BQ query is needed.
# Conservative list — when uncertain we default to the agent (safe).
_ANALYTICAL_RE = re.compile(
    r'\b('
    r'show\s+me|show\s+(?:a\s+|the\s+)?(?:chart|graph|table|data|list|breakdown|trend)'
    r'|chart|graph|plot|visuali[sz]e'
    r'|create\s+(?:a\s+)?(?:chart|graph|table|widget)'
    r'|give\s+me\s+(?:a\s+|the\s+)?(?:chart|graph|table|list|breakdown|data)'
    r'|list\s+(?:all\s+|the\s+)?(?:vendors?|projects?|resources?|contractors?|managers?)'
    r'|how\s+many|how\s+much'
    r'|what\s+(?:is\s+)?the\s+(?:total|sum|count|average|avg|breakdown)'
    r'|total\s+(?:spend|cost|budget|ytd|amount|headcount|fte|ftp)'
    r'|breakdown|distribution|split\s+by|group(?:ed)?\s+by'
    r'|by\s+(?:vendor|project|month|resource|manager|team|class|type)'
    r'|top\s+\d+|bottom\s+\d+|highest|lowest|most\s+expensive|ranking'
    r'|trend|over\s+time|by\s+month|monthly|quarterly'
    r'|compare|filter\s+(?:by|to|for)'
    r')\b',
    re.IGNORECASE,
)


def is_analytical(message: str) -> bool:
    """Return True if the message likely requires a live BigQuery query (agent loop).

    False → safe to use the fast chat_turn path (single Gemini call, no tools).
    Defaults to True when uncertain — the agent is always correct, just slower.
    """
    return bool(_ANALYTICAL_RE.search(message))


def _fetch_one_hint(column: str, limit: int, table_ref: str, token: str | None) -> tuple[str, list[str]]:
    """Fetch distinct values for one column, reading from cache when fresh."""
    now = time.monotonic()
    cached = _HINTS_CACHE.get(column)
    if cached and now - cached[0] < _HINTS_TTL:
        logger.debug(f"Hint cache hit for {column}")
        return column, cached[1]
    sql = f"SELECT DISTINCT {column} FROM `{table_ref}` WHERE {column} IS NOT NULL ORDER BY {column} LIMIT {limit}"
    rows = bigquery_client.run_query(sql, token)
    values = [str(r.get(column, "")) for r in rows if r.get(column)]
    _HINTS_CACHE[column] = (now, values)
    return column, values


def _build_contextual_hints(message: str, token: str | None) -> str:
    """Pre-fetch distinct values for columns whose keywords appear in the user message.

    Uses a per-column TTL cache and fires all matched columns in parallel so the
    total wait is one BQ round-trip (not N sequential ones).
    """
    if _CONVERSATIONAL_RE.match(message.strip()):
        return ""

    msg_lower = message.lower()
    table_ref = bigquery_client.TABLE_REFS[0] if bigquery_client.TABLE_REFS else ""
    if not table_ref:
        return ""

    matched = [
        (col, lim)
        for keywords, col, lim in _KEYWORD_COLUMNS
        if any(kw in msg_lower for kw in keywords)
    ]
    if not matched:
        return ""

    with ThreadPoolExecutor(max_workers=len(matched)) as pool:
        pairs = list(pool.map(
            lambda x: _fetch_one_hint(x[0], x[1], table_ref, token),
            matched,
        ))

    hints = [f"  {col}: {', '.join(vals)}" for col, vals in pairs if vals]
    if not hints:
        return ""
    logger.debug(f"Contextual hints built for {[col for col, _ in pairs if _]}")
    return "\n\nContextual values (exact strings to use in WHERE clauses):\n" + "\n".join(hints)


# ── WHERE-clause filter value correction ──────────────────────────────────────
# When a query returns 0 rows because the model used a non-existent string
# literal in a WHERE clause (wrong case, wrong value, abbreviation vs full name),
# we detect the bad values, fetch the real ones, and feed them back to the agent
# so it self-corrects on the next tool call.

_FILTER_RE = re.compile(
    # Matches: [alias.]ColumnName = 'value'  or  != 'value'
    # Does NOT match >, >=, <, <=, LIKE, IN, IS
    r'\b(?:\w+\.)?([\w]+)\s*(?:=|!=)\s*\'([^\']+)\'',
    re.IGNORECASE,
)

_IN_FILTER_RE = re.compile(
    # Matches: [alias.]ColumnName [NOT] IN ('val1', 'val2', ...)
    r'\b(?:\w+\.)?([\w]+)\s+(?:NOT\s+)?IN\s*\(\s*(\'[^\']*\'(?:\s*,\s*\'[^\']*\')*)\s*\)',
    re.IGNORECASE,
)

_SQL_KEYWORDS = frozenset({
    'AND', 'OR', 'NOT', 'NULL', 'TRUE', 'FALSE', 'IS', 'IN', 'LIKE',
    'BETWEEN', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'AS', 'ON',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS',
    'SELECT', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'BY', 'HAVING', 'LIMIT',
})


def _extract_string_filters(sql: str) -> dict[str, list[str]]:
    """Return {column: [values_used]} for string equality and IN filters in the WHERE clause."""
    # Isolate just the WHERE clause body (stop at GROUP BY / ORDER BY / LIMIT)
    m = re.search(
        r'\bWHERE\b([\s\S]+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bHAVING\b|$)',
        sql, re.IGNORECASE,
    )
    if not m:
        return {}
    where_body = m.group(1)
    result: dict[str, list[str]] = {}

    # col = 'value' and col != 'value'
    for col, val in _FILTER_RE.findall(where_body):
        if col.upper() in _SQL_KEYWORDS:
            continue
        result.setdefault(col, []).append(val)

    # col [NOT] IN ('val1', 'val2', ...)
    for col, vals_str in _IN_FILTER_RE.findall(where_body):
        if col.upper() in _SQL_KEYWORDS:
            continue
        vals = re.findall(r"'([^']*)'", vals_str)
        result.setdefault(col, []).extend(vals)

    return result


def _build_filter_correction_note(sql: str, token: str | None) -> str:
    """
    If the SQL has string equality WHERE filters, check whether the values used
    actually exist in the table.  For any value that does NOT exist, fetch the
    real distinct values and return a corrective note the agent can act on.

    Returns an empty string when everything looks fine.
    """
    filters = _extract_string_filters(sql)
    if not filters:
        return ""

    table_ref = bigquery_client.TABLE_REFS[0] if bigquery_client.TABLE_REFS else ""
    if not table_ref:
        return ""

    def _fetch_col_vals(col: str) -> tuple[str, list[str]]:
        # Prefer the hint cache to avoid extra BQ calls
        cached = _HINTS_CACHE.get(col)
        if cached and time.monotonic() - cached[0] < _HINTS_TTL:
            return col, cached[1]
        try:
            rows = bigquery_client.run_query(
                f"SELECT DISTINCT `{col}` FROM `{table_ref}` "
                f"WHERE `{col}` IS NOT NULL ORDER BY `{col}` LIMIT 40",
                token,
            )
            vals = [str(r[col]) for r in rows if r.get(col) is not None]
            _HINTS_CACHE[col] = (time.monotonic(), vals)
            return col, vals
        except Exception:
            return col, []  # column may not exist or may be in a subquery alias

    with ThreadPoolExecutor(max_workers=min(len(filters), 4)) as pool:
        actual_by_col = dict(pool.map(_fetch_col_vals, filters.keys()))

    corrections: list[str] = []
    for col, used_vals in filters.items():
        actual = actual_by_col.get(col, [])
        if not actual:
            continue
        actual_lower = {v.lower() for v in actual}
        wrong = [v for v in used_vals if v.lower() not in actual_lower]
        if wrong:
            sample = ", ".join(f"'{v}'" for v in actual[:20])
            corrections.append(
                f"  • {col}: used {[repr(w) for w in wrong]} — "
                f"actual values are: {sample}"
            )

    if not corrections:
        return ""

    return (
        "⚠️ Query returned 0 rows because of incorrect WHERE filter values.\n"
        + "\n".join(corrections)
        + "\nRetry using the exact values listed above."
    )


def fix_widget_sql(widget_def: dict, token: str | None = None) -> dict | None:
    """
    Run the widget's SQL.  If it returns 0 rows because of bad string filter
    values, ask Gemini to rewrite the SQL with the correct values and return
    a new widget_def.  Returns None if no fix was needed or possible.

    Used by the /api/query route (non-agent path) which has no feedback loop.
    """
    sql = widget_def.get("sql", "")
    if not sql:
        return None
    try:
        results = bigquery_client.run_query(sql, token)
    except Exception:
        return None  # BQ error — not a filter-value issue
    if results:
        return None  # query already works fine

    note = _build_filter_correction_note(sql, token)
    if not note:
        return None  # 0 rows but no detectable filter value problem

    logger.info(f"fix_widget_sql: retrying with filter correction for sql={sql[:80]!r}")
    try:
        return refine_widget(
            current_sql=sql,
            nl_modification=note + "\nFix the WHERE clause to use the correct values and return an updated widget JSON.",
        )
    except Exception as exc:
        logger.warning(f"fix_widget_sql: refine failed: {exc}")
        return None


def _build_agent_model():
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return GenerativeModel(
        model_name,
        tools=[_BQ_TOOL],
        system_instruction=_build_agent_system(),
    )


_AGENT_MODEL_INSTANCE: GenerativeModel | None = None


def _get_agent_model() -> GenerativeModel:
    """Return the cached agent model, building it once after schema is ready."""
    global _AGENT_MODEL_INSTANCE
    if _AGENT_MODEL_INSTANCE is None:
        _AGENT_MODEL_INSTANCE = _build_agent_model()
    return _AGENT_MODEL_INSTANCE


# Two-level BQ cache keyed by SQL:
#   _BQ_RESULT_CACHE  — truncated (≤50 rows) payload sent back to the model
#   _BQ_FULL_CACHE    — complete result list reused by the route to populate widget["data"]
# Both use a 60-second TTL so identical SQL within one conversation never hits BQ twice.
_BQ_RESULT_CACHE: dict[str, tuple[float, dict]] = {}
_BQ_FULL_CACHE: dict[str, tuple[float, list]] = {}
_BQ_RESULT_TTL = 60


def _execute_bq_call(fc, token: str | None) -> Part:
    """Run one BQ function call and return the function-response Part."""
    sql = fc.args.get("sql", "")

    now = time.monotonic()
    cached = _BQ_RESULT_CACHE.get(sql)
    if cached and now - cached[0] < _BQ_RESULT_TTL:
        logger.debug(f"Agent BQ cache hit: {sql[:60]!r}")
        return Part.from_function_response(name=fc.name, response=cached[1])

    logger.info(f"Agent tool call: sql={sql[:120]!r}…")
    try:
        results = bigquery_client.run_query(sql, token)
        total = len(results)
        _BQ_FULL_CACHE[sql] = (now, results)  # keep full result for route reuse
        resp_data: dict = {
            "status": "success",
            "row_count": total,
            "data": results[:50],  # model context capped at 50 rows
        }
        if total > 50:
            resp_data["truncated"] = True
            resp_data["note"] = (
                f"Results truncated to 50 of {total} total rows. "
                "Add more specific WHERE filters or GROUP BY to reduce the result set."
            )
            logger.warning(f"Agent tool: truncated {total}→50 rows for sql={sql[:80]!r}…")
        elif total == 0:
            # Check whether 0 rows is caused by a wrong hardcoded string filter value.
            # If so, attach corrective info so the agent rewrites the WHERE clause.
            correction = _build_filter_correction_note(sql, token)
            if correction:
                resp_data["note"] = correction
                logger.info(f"Agent tool: 0 rows + filter correction injected for sql={sql[:60]!r}")
            else:
                logger.info("Agent tool result: 0 rows")
        else:
            logger.info(f"Agent tool result: {total} rows")
    except Exception as exc:
        resp_data = {"status": "error", "error": str(exc)}
        logger.warning(f"Agent tool error: {exc}")

    _BQ_RESULT_CACHE[sql] = (now, resp_data)
    return Part.from_function_response(name=fc.name, response=resp_data)


_FINALIZE_PROMPT = (
    "You have gathered enough data. Respond with ONLY a raw JSON object — no markdown fences, "
    "no prose outside the JSON. Required schema:\n"
    '{"text": "<narrative>", "intent": "chart|table|text", '
    '"widget": {<optional>}, "suggested_questions": ["..."]}'
)


def _run_agent_loop(chat, user_prompt: str, token: str | None, max_tool_calls: int) -> dict:
    """Core synchronous agent loop. Returns the final parsed JSON dict."""
    response = chat.send_message(user_prompt)

    for _ in range(max_tool_calls):
        parts = response.candidates[0].content.parts
        fc_parts = [p for p in parts if getattr(p, "function_call", None) and getattr(p.function_call, "name", None)]
        if not fc_parts:
            break

        # Run all tool calls in this round concurrently
        with ThreadPoolExecutor(max_workers=len(fc_parts)) as pool:
            fn_responses = list(pool.map(lambda p: _execute_bq_call(p.function_call, token), fc_parts))

        response = chat.send_message(fn_responses)

    # If the loop exhausted max_tool_calls or the model returned no text,
    # send one finalize prompt to force a JSON text response.
    if not _response_text(response):
        logger.warning("Agent loop ended with no text response — sending finalize prompt")
        response = chat.send_message(_FINALIZE_PROMPT)

    return _safe_parse_agent_response(_response_text(response))


def agent_chat(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
    token: str | None = None,
    max_tool_calls: int = 4,
) -> dict:
    _require_model()

    glossary_ctx = _build_glossary_ctx(glossary_terms)

    contextual_hints = _build_contextual_hints(message, token)

    agent_model = _get_agent_model()

    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

    chat = agent_model.start_chat(history=vertex_history)
    user_prompt = f"{glossary_ctx}{contextual_hints}\n\nUser: {message}"
    return _run_agent_loop(chat, user_prompt, token, max_tool_calls)


async def agent_chat_stream(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
    token: str | None = None,
    max_tool_calls: int = 4,
):
    """Async generator that yields SSE-ready dicts during the agent loop.

    Yields:
        {"type": "status", "message": str}   — during tool calls
        {"type": "result",  "data": dict}    — final parsed JSON (one, last event)
        {"type": "error",   "message": str}  — on unrecoverable failure
    """
    _require_model()

    loop = asyncio.get_event_loop()

    glossary_ctx = _build_glossary_ctx(glossary_terms)

    yield {"type": "status", "message": "Preparing contextual hints…"}
    contextual_hints = await loop.run_in_executor(
        None, _build_contextual_hints, message, token
    )

    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

    agent_model = _get_agent_model()
    chat = agent_model.start_chat(history=vertex_history)
    user_prompt = f"{glossary_ctx}{contextual_hints}\n\nUser: {message}"

    yield {"type": "status", "message": "Analyzing your question…"}
    response = await loop.run_in_executor(None, chat.send_message, user_prompt)

    for step in range(max_tool_calls):
        parts = response.candidates[0].content.parts
        fc_parts = [p for p in parts if getattr(p, "function_call", None) and getattr(p.function_call, "name", None)]
        if not fc_parts:
            break

        n = len(fc_parts)
        label = f"{n} queries" if n > 1 else "query"
        yield {"type": "status", "message": f"Running {label} in parallel… (step {step + 1})"}

        # Fire all tool calls in this round concurrently
        fn_responses = list(await asyncio.gather(
            *[loop.run_in_executor(None, _execute_bq_call, p.function_call, token) for p in fc_parts]
        ))

        response = await loop.run_in_executor(None, chat.send_message, fn_responses)

    # If the loop exhausted max_tool_calls or the model returned no text,
    # send one finalize prompt to force a JSON text response.
    if not _response_text(response):
        logger.warning("Agent stream loop ended with no text response — sending finalize prompt")
        yield {"type": "status", "message": "Finalizing response…"}
        response = await loop.run_in_executor(None, chat.send_message, _FINALIZE_PROMPT)

    yield {"type": "status", "message": "Formatting response…"}
    try:
        result = _safe_parse_agent_response(_response_text(response))
        yield {"type": "result", "data": result}
    except Exception as exc:
        logger.error(f"Agent response parse failed: {exc}")
        yield {"type": "result", "data": {
            "text": "I encountered an issue formatting the response. Please try again.",
            "intent": "text",
            "suggested_questions": [],
        }}


def generate_pdf_description(title: str, chart_type: str, data_summary: str) -> str:
    _require_model()
    prompt = (
        f"You are writing a brief narrative for a PDF report section.\n"
        f"Widget title: {title}\nChart type: {chart_type}\nData summary: {data_summary}\n\n"
        f"Write 2-4 sentences of professional, human-readable insight about this data. "
        f"Focus on what the numbers mean for workforce or spend management. "
        f"Do not mention chart types or technical terms. Plain text only."
    )
    response = _model.generate_content(prompt)
    return response.text.strip()
