import os
import json
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
# BigQuery and Airflow always use user ADC only — SA fallback is Vertex AI only.

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

    # 2. Service-account JSON fallback (Vertex AI only — does not apply to BQ/Airflow)
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


<<<<<<< HEAD
=======
# ── Response parsing ───────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _require_model():
    if _model is None:
        raise RuntimeError(
            "Vertex AI model is not initialised. "
            "Check VERTEX_AI_PROJECT in .env and ensure credentials are configured."
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_widget(nl_query: str, glossary_terms: list[dict] | None = None) -> dict:
    _require_model()
    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']} → {t['definition']}" for t in glossary_terms)
        glossary_ctx = (
            f"\n\nUser-defined aliases (substitute these when interpreting the request — "
            f"treat each term as its mapped value in all contexts including table names, "
            f"column aliases, and descriptions):\n{lines}"
        )
    prompt = f"{_build_system_prompt()}{glossary_ctx}\n\nUser request: {nl_query}"
    response = _model.generate_content(prompt)
    return _parse_json(response.text)


>>>>>>> c411433 (Switch AI from Gemini API key to Vertex AI with IAM credentials)
def chat_turn(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
) -> dict:
    _require_model()
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

    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

<<<<<<< HEAD
    chat = _model.start_chat(history=gemini_history)
    prompt = f"{_CHAT_SYSTEM}{glossary_ctx}\n\nUser: {message}"
=======
    chat = _model.start_chat(history=vertex_history)
    prompt = f"{_build_chat_system()}{glossary_ctx}\n\nUser: {message}"
>>>>>>> c411433 (Switch AI from Gemini API key to Vertex AI with IAM credentials)
    response = chat.send_message(prompt)
    return _parse_json(response.text)


def refine_widget(current_sql: str, nl_modification: str, glossary_terms: list[dict] | None = None) -> dict:
    _require_model()
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


def _build_contextual_hints(message: str, token: str | None) -> str:
    """Pre-fetch distinct values for columns whose keywords appear in the user message."""
    msg_lower = message.lower()
    hints: list[str] = []

    # Use the first configured table for distinct-value queries
    table_ref = bigquery_client.TABLE_REFS[0] if bigquery_client.TABLE_REFS else ""
    if not table_ref:
        return ""

    for keywords, column, limit in _KEYWORD_COLUMNS:
        if any(kw in msg_lower for kw in keywords):
            try:
                sql = f"SELECT DISTINCT {column} FROM `{table_ref}` WHERE {column} IS NOT NULL ORDER BY {column} LIMIT {limit}"
                rows = bigquery_client.run_query(sql, token)
                values = [str(r.get(column, "")) for r in rows if r.get(column)]
                if values:
                    hints.append(f"  {column}: {', '.join(values)}")
                    logger.debug(f"Contextual hint for {column}: {len(values)} values")
            except Exception as exc:
                logger.debug(f"Contextual hint fetch failed for {column}: {exc}")

    if not hints:
        return ""
    return "\n\nContextual values (exact strings to use in WHERE clauses):\n" + "\n".join(hints)


def _build_agent_model():
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return GenerativeModel(
        model_name,
        tools=[_BQ_TOOL],
        system_instruction=_build_agent_system(),
    )


def _execute_bq_call(fc, token: str | None) -> Part:
    """Run one BQ function call and return the function-response Part."""
    sql = fc.args.get("sql", "")
    logger.info(f"Agent tool call: sql={sql[:120]!r}…")
    try:
        results = bigquery_client.run_query(sql, token)
        total = len(results)
        resp_data: dict = {
            "status": "success",
            "row_count": total,
            "data": results[:50],
        }
        if total > 50:
            resp_data["truncated"] = True
            resp_data["note"] = (
                f"Results truncated to 50 of {total} total rows. "
                "Add more specific WHERE filters or GROUP BY to reduce the result set."
            )
            logger.warning(f"Agent tool: truncated {total}→50 rows for sql={sql[:80]!r}…")
        else:
            logger.info(f"Agent tool result: {total} rows")
    except Exception as exc:
        resp_data = {"status": "error", "error": str(exc)}
        logger.warning(f"Agent tool error: {exc}")
    return Part.from_function_response(name=fc.name, response=resp_data)


def _run_agent_loop(chat, user_prompt: str, token: str | None, max_tool_calls: int) -> dict:
    """Core synchronous agent loop. Returns the final parsed JSON dict."""
    response = chat.send_message(user_prompt)

    for _ in range(max_tool_calls):
        parts = response.candidates[0].content.parts
        fc_parts = [p for p in parts if hasattr(p, "function_call") and p.function_call.name]
        if not fc_parts:
            break

        # Run all tool calls in this round concurrently
        with ThreadPoolExecutor(max_workers=len(fc_parts)) as pool:
            fn_responses = list(pool.map(lambda p: _execute_bq_call(p.function_call, token), fc_parts))

        response = chat.send_message(fn_responses)

    return _parse_json(response.text)


def agent_chat(
    message: str,
    history: list[dict],
    glossary_terms: list[dict] | None = None,
    token: str | None = None,
    max_tool_calls: int = 10,
) -> dict:
    _require_model()

    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']} → {t['definition']}" for t in glossary_terms)
        glossary_ctx = (
            f"\n\nUser-defined aliases (treat each term as its mapped value in all contexts — "
            f"table names, column names, abbreviations):\n{lines}"
        )

    contextual_hints = _build_contextual_hints(message, token)

    agent_model = _build_agent_model()

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
    max_tool_calls: int = 10,
):
    """Async generator that yields SSE-ready dicts during the agent loop.

    Yields:
        {"type": "status", "message": str}   — during tool calls
        {"type": "result",  "data": dict}    — final parsed JSON (one, last event)
        {"type": "error",   "message": str}  — on unrecoverable failure
    """
    _require_model()

    loop = asyncio.get_event_loop()

    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']} → {t['definition']}" for t in glossary_terms)
        glossary_ctx = (
            f"\n\nUser-defined aliases (treat each term as its mapped value in all contexts — "
            f"table names, column names, abbreviations):\n{lines}"
        )

    yield {"type": "status", "message": "Preparing contextual hints…"}
    contextual_hints = await loop.run_in_executor(
        None, _build_contextual_hints, message, token
    )

    agent_model = _build_agent_model()
    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

    chat = agent_model.start_chat(history=vertex_history)
    user_prompt = f"{glossary_ctx}{contextual_hints}\n\nUser: {message}"

    yield {"type": "status", "message": "Analyzing your question…"}
    response = await loop.run_in_executor(None, chat.send_message, user_prompt)

    for step in range(max_tool_calls):
        parts = response.candidates[0].content.parts
        fc_parts = [p for p in parts if hasattr(p, "function_call") and p.function_call.name]
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

    yield {"type": "status", "message": "Formatting response…"}
    try:
        result = _parse_json(response.text)
        yield {"type": "result", "data": result}
    except Exception as exc:
        yield {"type": "error", "message": f"Failed to parse AI response: {exc}"}


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
