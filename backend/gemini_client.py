import os
import json
import logging

import google.auth
import google.auth.transport.requests
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
    global _schema_cache
    if _schema_cache is None:
        try:
            _schema_cache = bigquery_client.build_schema_context()
        except Exception:
            _schema_cache = _FALLBACK_SCHEMA
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
"""


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

    chat = _model.start_chat(history=vertex_history)
    prompt = f"{_build_chat_system()}{glossary_ctx}\n\nUser: {message}"
    response = chat.send_message(prompt)
    return _parse_json(response.text)


def refine_widget(current_sql: str, nl_modification: str, glossary_terms: list[dict] | None = None) -> dict:
    _require_model()
    glossary_ctx = ""
    if glossary_terms:
        lines = "\n".join(f"  {t['term']}: {t['definition']}" for t in glossary_terms)
        glossary_ctx = f"\n\nDomain glossary:\n{lines}"

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
- If a query errors, try an alternative SQL approach before giving up.
"""


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

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    agent_model = GenerativeModel(
        model_name,
        tools=[_BQ_TOOL],
        system_instruction=_build_agent_system(),
    )

    vertex_history = [
        Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[Part.from_text(msg["content"])],
        )
        for msg in history
    ]

    chat = agent_model.start_chat(history=vertex_history)
    user_prompt = f"{glossary_ctx}\n\nUser: {message}" if glossary_ctx else f"User: {message}"
    response = chat.send_message(user_prompt)

    for _ in range(max_tool_calls):
        parts = response.candidates[0].content.parts
        fc_parts = [p for p in parts if hasattr(p, "function_call") and p.function_call.name]
        if not fc_parts:
            break

        fn_responses = []
        for p in fc_parts:
            fc = p.function_call
            sql = fc.args.get("sql", "")
            logger.info(f"Agent tool call: run_bigquery_query sql={sql[:120]!r}…")
            try:
                results = bigquery_client.run_query(sql, token)
                resp_data = {
                    "status": "success",
                    "row_count": len(results),
                    "data": results[:50],
                }
                logger.info(f"Agent tool result: {len(results)} rows")
            except Exception as exc:
                resp_data = {"status": "error", "error": str(exc)}
                logger.warning(f"Agent tool error: {exc}")

            fn_responses.append(
                Part.from_function_response(name=fc.name, response=resp_data)
            )

        response = chat.send_message(fn_responses)

    return _parse_json(response.text)


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
