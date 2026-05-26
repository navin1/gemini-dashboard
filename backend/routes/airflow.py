"""
Airflow / Cloud Composer proxy routes.

All calls are proxied through the backend so the frontend never talks to
Composer directly (avoids CORS) and auth is handled server-side.

Auth priority for each request:
  1. Bearer token from the user's Authorization header  (forwarded as-is)
  2. Service account / ADC credentials  (GOOGLE_APPLICATION_CREDENTIALS or ADC)

Configured via .env:
  AIRFLOW_ENVIRONMENTS = Dev:https://url1,QA:https://url2
  AIRFLOW_DAGS         = dag_id_1,dag_id_2
"""

import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from dotenv import load_dotenv

from auth import get_request_token

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/api/airflow", tags=["airflow"])

# ── Config parsing ─────────────────────────────────────────────────────────────

def _parse_environments() -> list[dict]:
    raw = os.getenv("AIRFLOW_ENVIRONMENTS", "").strip()
    if not raw:
        return []
    envs = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        name, url = entry.split(":", 1)
        envs.append({"name": name.strip(), "url": url.strip().rstrip("/")})
    return envs


def _parse_dags() -> list[str]:
    raw = os.getenv("AIRFLOW_DAGS", "").strip()
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


_ENVIRONMENTS = _parse_environments()
_DAGS = _parse_dags()

_ENV_MAP: dict[str, str] = {e["name"]: e["url"] for e in _ENVIRONMENTS}


def _resolve_url(env_name: str) -> str:
    url = _ENV_MAP.get(env_name)
    if not url:
        names = list(_ENV_MAP.keys())
        raise HTTPException(status_code=400, detail=f"Unknown environment '{env_name}'. Available: {names}")
    return url


# ── Auth helper ────────────────────────────────────────────────────────────────

async def _airflow_headers(token: Optional[str]) -> dict[str, str]:
    """
    Build Authorization headers for Airflow API calls.
    Tries the user's Bearer token first; falls back to ADC/service account.
    """
    if token:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Fallback: use google-auth to get a fresh ADC/service-account token
    try:
        import google.auth
        import google.auth.transport.requests as ga_requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        req = ga_requests.Request()
        creds.refresh(req)
        return {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"No valid credentials found. Set GOOGLE_APPLICATION_CREDENTIALS or log in. ({exc})",
        )


# ── Generic proxy helper ───────────────────────────────────────────────────────

async def _airflow_get(url: str, path: str, token: Optional[str], params: dict | None = None) -> dict:
    headers = await _airflow_headers(token)
    full_url = f"{url}/api/v1{path}"
    logger.info(f"Airflow GET {full_url} params={params or {}}")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=True) as client:
            resp = await client.get(full_url, headers=headers, params=params or {})
        ms = (time.perf_counter() - t0) * 1000
    except httpx.ConnectError as exc:
        ms = (time.perf_counter() - t0) * 1000
        logger.error(f"Airflow connect failed → {full_url} after {ms:.0f}ms: {exc}")
        raise HTTPException(status_code=502, detail=f"Cannot reach Airflow at {url}. Check AIRFLOW_ENVIRONMENTS in .env. ({type(exc).__name__}: {exc})")
    except httpx.TimeoutException as exc:
        ms = (time.perf_counter() - t0) * 1000
        logger.error(f"Airflow timeout → {full_url} after {ms:.0f}ms: {exc}")
        raise HTTPException(status_code=504, detail=f"Airflow request timed out after 20s: {url}{path}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        logger.exception(f"Airflow unexpected error → {full_url} after {ms:.0f}ms")
        raise HTTPException(status_code=500, detail=f"Airflow request failed: {exc}")

    if resp.status_code == 401:
        logger.warning(f"Airflow 401 → {full_url}")
        raise HTTPException(status_code=401, detail="Airflow authentication failed. Check your token or credentials.")
    if resp.status_code == 403:
        logger.warning(f"Airflow 403 → {full_url}")
        raise HTTPException(status_code=403, detail="Access denied. Check IAP / Composer permissions.")
    if resp.status_code == 404:
        logger.warning(f"Airflow 404 → {full_url}")
        raise HTTPException(status_code=404, detail=f"Airflow resource not found: {path}")
    if not resp.is_success:
        logger.warning(f"Airflow {resp.status_code} → {full_url} in {ms:.0f}ms: {resp.text[:200]}")
        raise HTTPException(status_code=resp.status_code, detail=f"Airflow error: {resp.text[:300]}")

    logger.info(f"Airflow {resp.status_code} → {full_url} in {ms:.0f}ms")
    return resp.json()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/config")
async def airflow_config():
    """Return the list of configured environments and DAG IDs."""
    return {
        "environments": _ENVIRONMENTS,
        "dags": _DAGS,
        "default_env": _ENVIRONMENTS[0]["name"] if _ENVIRONMENTS else None,
    }


@router.get("/dags/status")
async def dags_status(
    env: str = Query(..., description="Environment name, e.g. Dev"),
    token: Optional[str] = Depends(get_request_token),
):
    """
    Return last-run status for every configured DAG in AIRFLOW_DAGS.
    Response: [{dag_id, state, last_run_time}]
    """
    base_url = _resolve_url(env)

    async def fetch_one(dag_id: str) -> dict:
        try:
            data = await _airflow_get(
                base_url,
                f"/dags/{dag_id}/dagRuns",
                token,
                params={"limit": "1", "order_by": "-execution_date"},
            )
            runs = data.get("dag_runs", [])
            if runs:
                run = runs[0]
                return {
                    "dag_id": dag_id,
                    "state": run.get("state"),
                    "last_run_time": run.get("execution_date"),
                }
            return {"dag_id": dag_id, "state": None, "last_run_time": None}
        except HTTPException as exc:
            return {"dag_id": dag_id, "state": "error", "last_run_time": None, "error": exc.detail}

    import asyncio
    results = await asyncio.gather(*[fetch_one(dag_id) for dag_id in _DAGS])
    return {"dags": list(results), "env": env}


@router.get("/dag/{dag_id}/meta")
async def dag_meta(
    dag_id: str,
    env: str = Query(...),
    token: Optional[str] = Depends(get_request_token),
):
    """
    DAG metadata: schedule_interval, is_paused, last run info, last success run.
    Mirrors the Chrome extension's fetchDagMeta() — 3 parallel Airflow calls.
    """
    import asyncio
    base_url = _resolve_url(env)
    dag_data, runs_data, success_data = await asyncio.gather(
        _airflow_get(base_url, f"/dags/{dag_id}", token),
        _airflow_get(base_url, f"/dags/{dag_id}/dagRuns", token,
                     params={"limit": "1", "order_by": "-execution_date"}),
        _airflow_get(base_url, f"/dags/{dag_id}/dagRuns", token,
                     params={"limit": "1", "order_by": "-execution_date", "state": "success"}),
    )
    last_run     = (runs_data.get("dag_runs")   or [])[0] if runs_data.get("dag_runs")   else None
    success_run  = (success_data.get("dag_runs") or [])[0] if success_data.get("dag_runs") else None
    return {
        "dag_id":              dag_id,
        "env":                 env,
        "schedule_interval":   dag_data.get("schedule_interval"),
        "is_paused":           bool(dag_data.get("is_paused")),
        "last_run_id":         last_run.get("dag_run_id")   if last_run    else None,
        "last_run_state":      last_run.get("state")         if last_run    else None,
        "last_run_start":      last_run.get("start_date")    if last_run    else None,
        "last_success_run_id": success_run.get("dag_run_id") if success_run else None,
    }


@router.post("/dag/{dag_id}/trigger")
async def trigger_dag(
    dag_id: str,
    env: str = Query(...),
    token: Optional[str] = Depends(get_request_token),
):
    """Trigger a new DAG run. Mirrors the Chrome extension's triggerDagRun()."""
    base_url = _resolve_url(env)
    headers  = await _airflow_headers(token)
    full_url = f"{base_url}/api/v1/dags/{dag_id}/dagRuns"
    logger.info(f"Airflow POST {full_url}")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=True) as client:
            resp = await client.post(full_url, headers=headers, json={})
        ms = (time.perf_counter() - t0) * 1000
    except httpx.ConnectError as exc:
        ms = (time.perf_counter() - t0) * 1000
        logger.error(f"Airflow connect failed → {full_url} after {ms:.0f}ms: {exc}")
        raise HTTPException(status_code=502, detail=f"Cannot reach Airflow at {base_url}: {exc}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        logger.exception(f"Airflow trigger error → {full_url} after {ms:.0f}ms")
        raise HTTPException(status_code=500, detail=f"Trigger failed: {exc}")
    if not resp.is_success:
        logger.warning(f"Airflow trigger {resp.status_code} → {full_url}: {resp.text[:200]}")
        raise HTTPException(status_code=resp.status_code, detail=f"Trigger failed: {resp.text[:300]}")
    data = resp.json()
    logger.info(f"Airflow trigger OK → {dag_id} run_id={data.get('dag_run_id')} in {ms:.0f}ms")
    return {
        "dag_id":         dag_id,
        "env":            env,
        "run_id":         data.get("dag_run_id"),
        "execution_date": data.get("execution_date"),
    }


@router.get("/dag/{dag_id}/runs/{run_id}/state")
async def dag_run_state(
    dag_id: str,
    run_id: str,
    env: str = Query(...),
    token: Optional[str] = Depends(get_request_token),
):
    """State of a specific run — used to poll after trigger. Mirrors fetchRunState()."""
    base_url = _resolve_url(env)
    data = await _airflow_get(base_url, f"/dags/{dag_id}/dagRuns/{run_id}", token)
    return {"dag_id": dag_id, "run_id": run_id, "env": env, "state": data.get("state")}


@router.get("/dag/{dag_id}/runs")
async def dag_runs(
    dag_id: str,
    env: str = Query(...),
    limit: int = Query(5, ge=1, le=25),
    token: Optional[str] = Depends(get_request_token),
):
    """Return the last `limit` runs for a DAG (default 5)."""
    base_url = _resolve_url(env)
    data = await _airflow_get(
        base_url,
        f"/dags/{dag_id}/dagRuns",
        token,
        params={"limit": str(limit), "order_by": "-execution_date"},
    )
    runs = data.get("dag_runs", [])
    return {
        "dag_id": dag_id,
        "env": env,
        "runs": [
            {
                "run_id": r.get("dag_run_id"),
                "state": r.get("state"),
                "execution_date": r.get("execution_date"),
                "start_date": r.get("start_date"),
                "end_date": r.get("end_date"),
            }
            for r in runs
        ],
    }


@router.get("/dag/{dag_id}/tasks")
async def dag_tasks(
    dag_id: str,
    env: str = Query(...),
    run_id: Optional[str] = Query(None, description="Run ID to fetch task states for"),
    token: Optional[str] = Depends(get_request_token),
):
    """
    Return task structure + task instance states for the given run.
    If run_id is omitted, fetches the most recent run.
    """
    base_url = _resolve_url(env)
    import asyncio

    # Fetch task structure
    task_data = await _airflow_get(base_url, f"/dags/{dag_id}/tasks", token)
    tasks_raw = task_data.get("tasks", [])
    tasks = [
        {
            "task_id": str(t.get("task_id", "")),
            "operator": str((t.get("class_ref") or {}).get("class_name", "")),
            "downstream_task_ids": t.get("downstream_task_ids", []),
            "state": None,
        }
        for t in tasks_raw
    ]

    # Resolve run_id if not provided
    effective_run_id = run_id
    if not effective_run_id:
        try:
            runs_data = await _airflow_get(
                base_url,
                f"/dags/{dag_id}/dagRuns",
                token,
                params={"limit": "1", "order_by": "-execution_date"},
            )
            dag_runs_list = runs_data.get("dag_runs", [])
            if dag_runs_list:
                effective_run_id = dag_runs_list[0].get("dag_run_id")
        except Exception:
            pass

    # Fetch task instance states
    if effective_run_id:
        try:
            ti_data = await _airflow_get(
                base_url,
                f"/dags/{dag_id}/dagRuns/{effective_run_id}/taskInstances",
                token,
            )
            state_map = {
                ti.get("task_id"): ti.get("state")
                for ti in ti_data.get("task_instances", [])
            }
            for t in tasks:
                t["state"] = state_map.get(t["task_id"])
        except Exception:
            pass

    return {"dag_id": dag_id, "env": env, "run_id": effective_run_id, "tasks": tasks}


@router.get("/task/{dag_id}/{task_id}/sql")
async def task_sql(
    dag_id: str,
    task_id: str,
    env: str = Query(...),
    run_id: Optional[str] = Query(None),
    token: Optional[str] = Depends(get_request_token),
):
    """
    Fetch SQL for a task: tries rendered SQL from run instances first,
    falls back to raw task definition.
    """
    base_url = _resolve_url(env)

    raw_sql: Optional[str] = None
    rendered_sql: Optional[str] = None
    source = "none"

    # ── Attempt 1: raw SQL from task definition ──────────────────────────────
    try:
        task_def = await _airflow_get(base_url, f"/dags/{dag_id}/tasks/{task_id}", token)
        for key in ("sql", "query", "bql"):
            val = task_def.get(key)
            if isinstance(val, str) and val.strip() and not val.strip().endswith(".sql"):
                raw_sql = val.strip()
                break
    except Exception:
        pass

    # ── Attempt 2: rendered SQL from task instances ──────────────────────────
    async def try_render_from_run(rid: str) -> Optional[str]:
        try:
            ti = await _airflow_get(
                base_url,
                f"/dags/{dag_id}/dagRuns/{rid}/taskInstances/{task_id}",
                token,
            )
            for key in ("rendered_fields", "rendered_map_index"):
                rf = ti.get(key)
                if isinstance(rf, dict):
                    for sql_key in ("sql", "query", "bql"):
                        val = rf.get(sql_key)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
            # Direct rendered_fields at top level (Airflow 2.x)
            rf = ti.get("rendered_fields")
            if isinstance(rf, dict):
                for sql_key in ("sql", "query", "bql"):
                    val = rf.get(sql_key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except Exception:
            pass
        return None

    if run_id:
        rendered_sql = await try_render_from_run(run_id)

    if not rendered_sql:
        try:
            runs_data = await _airflow_get(
                base_url,
                f"/dags/{dag_id}/dagRuns",
                token,
                params={"limit": "10", "order_by": "-execution_date", "state": "success"},
            )
            for run in runs_data.get("dag_runs", []):
                rid = run.get("dag_run_id", "")
                if rid and rid != run_id:
                    rendered_sql = await try_render_from_run(rid)
                    if rendered_sql:
                        break
        except Exception:
            pass

    chosen = rendered_sql or raw_sql
    if rendered_sql:
        source = "rendered"
    elif raw_sql:
        source = "raw"

    return {
        "dag_id": dag_id,
        "task_id": task_id,
        "env": env,
        "sql": chosen,
        "source": source,
        "truncated": False,
    }
