import json
import re
import base64
import tempfile
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from fastapi.responses import FileResponse
from schemas import PDFRequest
import gemini_client

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), '..', 'assets')

# ── Margin constants ─────────────────────────────────────────────────────────
# Change ONLY these two values to control body/header gap on every content page.
# Rule: both @page CSS (line ~397) and Playwright margin= (line ~460) read these.
_MARGIN_TOP    = "72px"   # header height (52px) + breathing room
_MARGIN_BOTTOM = "50px"   # footer height (36px) + breathing room

def _logo_b64() -> str:
    try:
        with open(os.path.join(_ASSETS_DIR, 'logo.png'), 'rb') as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ''

def _header_html() -> str:
    logo = _logo_b64()
    est  = timezone(timedelta(hours=-5))
    ts   = datetime.now(tz=est).strftime('%m-%d-%Y %H:%M:%S') + ' EST'
    img  = (f'<img src="data:image/png;base64,{logo}" '
            f'style="height:28px;display:block;" />'
            if logo else
            '<span style="font-size:10pt;font-weight:700;color:#0F172A;">Company</span>')
    return f"""
<div style="width:100%;display:flex;align-items:center;justify-content:space-between;
     padding:0 56px;font-family:Arial,Helvetica,sans-serif;
     height:52px;box-sizing:border-box;">
  {img}
  <div style="text-align:right;line-height:1.3;">
    <div style="font-size:8.5pt;font-weight:700;color:#0F172A;letter-spacing:1.2px;">EXECUTIVE REPORT</div>
    <div style="font-size:7pt;color:#CBD5E1;margin-top:2px;">{ts}</div>
  </div>
</div>"""

def _footer_html() -> str:
    return """
<div style="width:100%;display:flex;align-items:center;justify-content:space-between;
     padding:0 56px;font-family:Arial,Helvetica,sans-serif;
     height:36px;box-sizing:border-box;">
  <span style="font-size:6.5pt;color:#CBD5E1;">Confidential</span>
  <span style="font-size:6.5pt;color:#CBD5E1;">
    Page <span class="pageNumber"></span> of <span class="totalPages"></span>
  </span>
</div>"""

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

_MONEY_RE = re.compile(r'spend|dollar|amount|budget|fee|cost|ytd|capital|expense|salary|rate', re.IGNORECASE)

PDF_PALETTE = [
    '#2563EB', '#16A34A', '#D97706', '#DC2626', '#7C3AED',
    '#0891B2', '#DB2777', '#65A30D', '#EA580C', '#0D9488',
    '#9333EA', '#CA8A04', '#1D4ED8', '#15803D',
]


def _fmt_dollars(val) -> str:
    try:
        v = float(val)
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:,.2f}"
    except Exception:
        return str(val)


def _fmt_number(val) -> str:
    try:
        return f"{float(val):,.2f}"
    except Exception:
        return str(val)


def _pivot(data, x_key, val_key, color_field):
    seen_cats: list[str] = []
    for r in data:
        c = str(r.get(color_field, ''))
        if c not in seen_cats:
            seen_cats.append(c)
    by_x: dict = {}
    all_x: list[str] = []
    for row in data:
        xv = str(row.get(x_key, ''))
        if xv not in by_x:
            by_x[xv] = {}
            all_x.append(xv)
        cat = str(row.get(color_field, ''))
        by_x[xv][cat] = row.get(val_key, 0)
    return all_x, seen_cats, by_x


def _num_keys(row: dict, exclude: list[str]) -> list[str]:
    return [k for k in row if k not in exclude and isinstance(row[k], (int, float))]


def _build_chartjs_config(widget: dict) -> dict | None:
    chart_type = widget.get('chart_type', 'table')
    data = widget.get('data', [])
    x_axis = widget.get('x_axis')
    y_axis = widget.get('y_axis') or []
    color_field = widget.get('color_field')
    stacked = widget.get('stacked', False) or chart_type == 'stacked_bar'
    secondary_y = widget.get('secondary_y')

    if not data or chart_type in ('table', 'kpi'):
        return None

    x_key = x_axis or list(data[0].keys())[0]
    P = PDF_PALETTE
    is_money = bool(_MONEY_RE.search(' '.join(y_axis)))

    legend_opts = {
        'position': 'bottom',
        'labels': {'font': {'size': 8, 'family': 'Inter, Segoe UI, Arial'}, 'boxWidth': 10, 'padding': 12},
    }
    grid_opts = {
        'x': {'grid': {'display': False}, 'ticks': {'font': {'size': 8}, 'maxRotation': 45, 'minRotation': 0}},
        'y': {'grid': {'color': 'rgba(0,0,0,0.06)'}, 'ticks': {'font': {'size': 8}}},
    }
    base_opts: dict = {
        'responsive': True,
        'maintainAspectRatio': False,
        'plugins': {'legend': legend_opts},
        'scales': grid_opts,
    }

    if chart_type in ('bar', 'stacked_bar', 'horizontal_bar'):
        is_horiz = chart_type == 'horizontal_bar'
        if color_field and any(color_field in r for r in data):
            val_key = (y_axis[0] if y_axis else None) or next(
                (k for k in data[0] if k not in (x_key, color_field) and isinstance(data[0][k], (int, float))), None
            )
            labels, cats, by_x = _pivot(data, x_key, val_key, color_field)
            datasets = [
                {'label': c, 'data': [by_x[x].get(c, 0) for x in labels],
                 'backgroundColor': P[i % len(P)], 'borderRadius': 4}
                for i, c in enumerate(cats)
            ]
        else:
            y_keys = y_axis or _num_keys(data[0], [x_key, 'm_ord'])[:6]
            labels = [str(r.get(x_key, '')) for r in data]
            datasets = [
                {'label': k, 'data': [r.get(k, 0) for r in data],
                 'backgroundColor': P[i % len(P)], 'borderRadius': 4}
                for i, k in enumerate(y_keys)
            ]
        opts = json.loads(json.dumps(base_opts))
        opts['scales']['x']['stacked'] = stacked
        opts['scales']['y']['stacked'] = stacked
        if is_horiz:
            opts['indexAxis'] = 'y'
            opts['scales']['x']['grid'] = {'color': 'rgba(0,0,0,0.05)'}
            opts['scales']['y']['grid'] = {'display': False}
        return {'type': 'bar', 'data': {'labels': labels, 'datasets': datasets}, 'options': opts, '_money': is_money}

    if chart_type == 'line':
        if color_field and any(color_field in r for r in data):
            val_key = (y_axis[0] if y_axis else None) or next(
                (k for k in data[0] if k not in (x_key, color_field) and isinstance(data[0][k], (int, float))), None
            )
            labels, cats, by_x = _pivot(data, x_key, val_key, color_field)
            datasets = [
                {'label': c, 'data': [by_x[x].get(c, 0) for x in labels],
                 'borderColor': P[i % len(P)], 'backgroundColor': P[i % len(P)],
                 'fill': False, 'borderWidth': 1, 'tension': 0.2, 'pointRadius': 0}
                for i, c in enumerate(cats)
            ]
        else:
            y_keys = y_axis or _num_keys(data[0], [x_key, 'm_ord'])[:6]
            labels = [str(r.get(x_key, '')) for r in data]
            datasets = [
                {'label': k, 'data': [r.get(k, 0) for r in data],
                 'borderColor': P[i % len(P)], 'backgroundColor': P[i % len(P)],
                 'fill': False, 'borderWidth': 1, 'tension': 0.2, 'pointRadius': 0}
                for i, k in enumerate(y_keys)
            ]
        return {'type': 'line', 'data': {'labels': labels, 'datasets': datasets}, 'options': base_opts, '_money': is_money}

    if chart_type in ('donut', 'pie'):
        val_key = (y_axis[0] if y_axis else None) or next(
            (k for k in data[0] if isinstance(data[0][k], (int, float))), list(data[0].keys())[-1]
        )
        labels = [str(r.get(x_key, '')) for r in data]
        values = [r.get(val_key, 0) for r in data]
        return {
            'type': 'doughnut' if chart_type == 'donut' else 'pie',
            'data': {'labels': labels, 'datasets': [{'data': values, 'backgroundColor': P[:len(values)], 'hoverOffset': 4}]},
            'options': {
                'responsive': True, 'maintainAspectRatio': False,
                'plugins': {'legend': {'position': 'right', 'labels': {'font': {'size': 13}, 'boxWidth': 14, 'padding': 16}}},
            },
            '_money': is_money,
        }

    if chart_type == 'combo':
        y_keys = y_axis or _num_keys(data[0], [x_key, 'm_ord'])[:4]
        bar_keys = [k for k in y_keys if k != secondary_y]
        labels = [str(r.get(x_key, '')) for r in data]
        datasets = [
            {'type': 'bar', 'label': k, 'data': [r.get(k, 0) for r in data],
             'backgroundColor': P[i % len(P)], 'yAxisID': 'y', 'borderRadius': 4}
            for i, k in enumerate(bar_keys)
        ]
        if secondary_y:
            datasets.append({
                'type': 'line', 'label': secondary_y,
                'data': [r.get(secondary_y, 0) for r in data],
                'borderColor': P[len(bar_keys) % len(P)], 'backgroundColor': P[len(bar_keys) % len(P)],
                'fill': False, 'tension': 0.3, 'pointRadius': 3, 'yAxisID': 'y1',
            })
        return {
            'type': 'bar',
            'data': {'labels': labels, 'datasets': datasets},
            'options': {
                'responsive': True, 'maintainAspectRatio': False,
                'plugins': {'legend': legend_opts},
                'scales': {
                    'x': {'grid': {'display': False}, 'ticks': {'font': {'size': 12}, 'maxRotation': 45, 'minRotation': 0}},
                    'y': {'position': 'left', 'grid': {'color': 'rgba(0,0,0,0.06)'}, 'ticks': {'font': {'size': 12}}},
                    'y1': {'position': 'right', 'grid': {'drawOnChartArea': False}, 'ticks': {'font': {'size': 12}}},
                },
            },
            '_money': is_money,
        }

    return None


def _build_table_html(data: list, max_rows: int = 20) -> str:
    if not data:
        return ''
    headers = list(data[0].keys())
    num_cols = {h for h in headers if isinstance(data[0].get(h), (int, float)) and not isinstance(data[0].get(h), bool)}
    ra = 'style="text-align:right"'
    heads = ''.join(
        f'<th {ra}>{h.replace("_", " ")}</th>' if h in num_cols else f'<th>{h.replace("_", " ")}</th>'
        for h in headers
    )
    rows = ''
    for row in data[:max_rows]:
        cells = ''
        for h in headers:
            v = row.get(h, '')
            hk = h.lower()
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                v = _fmt_dollars(v) if hk.endswith(('spend', 'dollars', 'amount', 'budget', 'account')) else _fmt_number(v)
            align = ra if h in num_cols else ''
            cells += f'<td {align}>{v}</td>'
        rows += f'<tr>{cells}</tr>'
    note = f'<p class="truncate-note">Showing top {max_rows} of {len(data)} rows</p>' if len(data) > max_rows else ''
    return f'<div class="data-table"><table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table>{note}</div>'


def _build_html(title: str, tab_name: str, widgets: list[dict], date_str: str, include_cover: bool = True) -> str:
    chart_configs: list[dict] = []
    sections = ''

    for idx, w in enumerate(widgets):
        widget_title = w.get('title', '')
        chart_type = w.get('chart_type', 'table')
        description = w.get('ai_description', '')
        data = w.get('data', [])

        if not description and data:
            try:
                description = gemini_client.generate_pdf_description(
                    widget_title, chart_type, json.dumps(data[:5], default=str)
                )
            except Exception:
                description = 'Analysis based on workforce and spend data.'

        cfg = _build_chartjs_config(w)
        chart_id = f'chart_{idx}'
        chart_html = ''
        if cfg:
            chart_configs.append({'id': chart_id, 'config': cfg})
            aspect = 'chart-wide' if chart_type in ('bar', 'stacked_bar', 'line', 'combo', 'horizontal_bar') else 'chart-sq'
            chart_html = f'<div class="chart-wrap {aspect}"><canvas id="{chart_id}"></canvas></div>'

        table_html = _build_table_html(data)
        insight_html = (
            f'<div class="insight"><span class="insight-label">AI Insight</span><p>{description}</p></div>'
            if description else ''
        )

        sections += f'''
  <div class="widget-section">
    <div class="widget-header">
      <h2>{widget_title}</h2>
      <span class="badge">{chart_type.replace("_", " ").title()}</span>
    </div>
    <div class="widget-body">
      {chart_html}
      {insight_html}
      {table_html}
    </div>
  </div>'''

    charts_js = ''
    if chart_configs:
        configs_json = json.dumps(chart_configs, default=str)
        charts_js = f'''<script>
(function() {{
  if (typeof Chart === 'undefined') {{ window.chartsReady = true; return; }}
  Chart.defaults.font.family = "Inter, Segoe UI, Arial, sans-serif";
  function numFmt(v, money) {{
    var a = Math.abs(v), p = money ? '$' : '';
    if (a >= 1e9) return p + (v/1e9).toFixed(1) + 'B';
    if (a >= 1e6) return p + (v/1e6).toFixed(1) + 'M';
    if (a >= 1e3) return p + Math.round(v/1e3) + 'K';
    return p + Math.round(v).toLocaleString();
  }}
  var items = {configs_json};
  items.forEach(function(item) {{
    var el = document.getElementById(item.id);
    if (!el) return;
    var money = item.config._money === true;
    var scales = (item.config.options || {{}}).scales || {{}};
    var isHoriz = (item.config.options || {{}}).indexAxis === 'y';
    var valAxis = isHoriz ? scales.x : scales.y;
    if (valAxis) valAxis.ticks = Object.assign(valAxis.ticks || {{}}, {{
      callback: function(v) {{ return numFmt(v, false); }}
    }});
    if (scales.y1) scales.y1.ticks = Object.assign(scales.y1.ticks || {{}}, {{
      callback: function(v) {{ return numFmt(v, false); }}
    }});
    new Chart(el, item.config);
  }});
  window.chartsReady = true;
}})();
</script>'''

    page_first_rule = '@page :first { margin:0; }' if include_cover else ''
    cover_block = f'''
<div class="cover">
  <div class="cover-rule-top"></div>
  <p class="cover-eyebrow">Workforce Analytics · Executive Report</p>
  <h1>{title}</h1>
  <p class="sub">{tab_name}</p>
  <div class="cover-divider"></div>
  <div class="cover-meta">
    <div class="cover-meta-item"><label>Report Date</label><span>{date_str}</span></div>
    <div class="cover-meta-item"><label>Analysis</label><span>EDA Team</span></div>
  </div>
  <div class="cover-foot">Confidential</div>
</div>''' if include_cover else ''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Inter','Segoe UI',Arial,sans-serif; font-size:10pt; color:#1E293B; background:#fff; }}

/* ── Cover ─────────────────────────────────── */
.cover {{
  page-break-after:always;
  min-height:100vh; display:flex; flex-direction:column; justify-content:center;
  padding:80px 72px; background:#fff; position:relative;
  border-left:6px solid #991B1B;
}}
.cover-rule-top {{ position:absolute; top:0; left:0; right:0; height:3px; background:linear-gradient(90deg,#991B1B,#EF4444,#FCA5A5); }}
.cover-eyebrow {{ font-size:8pt; font-weight:600; letter-spacing:2.5px; text-transform:uppercase; color:#EF4444; margin-bottom:20px; }}
.cover h1 {{ font-size:28pt; font-weight:700; line-height:1.2; color:#0F172A; margin-bottom:10px; }}
.cover .sub {{ font-size:13pt; color:#64748B; margin-bottom:56px; font-weight:300; }}
.cover-divider {{ height:1px; background:#E2E8F0; margin:0 0 40px; }}
.cover-meta {{ display:flex; gap:48px; margin-bottom:auto; }}
.cover-meta-item label {{ display:block; font-size:7.5pt; text-transform:uppercase; letter-spacing:1px; color:#94A3B8; margin-bottom:5px; }}
.cover-meta-item span {{ font-size:10pt; color:#334155; font-weight:500; }}
.cover-foot {{ position:absolute; bottom:48px; right:72px; font-size:7.5pt; color:#CBD5E1; letter-spacing:0.5px; }}

/* ── Content ──────────────────────────────── */
.content {{ padding:0 56px 48px 56px; }}

/* ── Widget ───────────────────────────────── */
.widget-section {{ margin-bottom:44px; border:1px solid #E2E8F0; border-radius:10px; }}
.widget-section + .widget-section {{ page-break-before:always; margin-top:0; }}
.widget-header {{
  background:#FFF5F5; border-bottom:1px solid #FEE2E2;
  border-left:4px solid #991B1B;
  padding:13px 18px; display:flex; align-items:center; justify-content:space-between;
}}
.widget-header h2 {{ font-size:11pt; font-weight:600; color:#0F172A; }}
.badge {{ background:#FFF1F2; color:#991B1B; font-size:7pt; font-weight:600; padding:3px 10px; border-radius:20px; letter-spacing:0.5px; text-transform:uppercase; }}
.widget-body {{ padding:20px 22px; align-items:center; }}

/* ── Charts ───────────────────────────────── */
.chart-wrap {{ margin-bottom:18px; break-inside:avoid; page-break-inside:avoid; }}
.chart-wide {{ width:40%; height:240px; margin-left:50px; }}
.chart-sq   {{ width:32%; height:240px; margin-left:50px; }}
canvas {{ display:block; }}

/* ── AI Insight ───────────────────────────── */
.insight {{ background:#FFF5F5; border-left:3px solid #EF4444; padding:10px 14px; border-radius:0 6px 6px 0; margin-bottom:16px; }}
.insight-label {{ display:block; font-size:7pt; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:#DC2626; margin-bottom:4px; }}
.insight p {{ font-size:9pt; color:#334155; line-height:1.65; }}

/* ── Data table ───────────────────────────── */
.data-table {{ border:1px solid #E2E8F0; border-radius:6px; overflow:hidden; }}
table {{ width:100%; border-collapse:collapse; font-size:7.5pt; }}
th {{ background:#F1F5F9; color:#475569; font-weight:600; text-align:left; padding:7px 10px; border-bottom:2px solid #E2E8F0; text-transform:uppercase; font-size:6.5pt; letter-spacing:0.6px; white-space:nowrap; }}
td {{ padding:5px 10px; border-bottom:1px solid #F1F5F9; color:#1E293B; white-space:nowrap; }}
tr:last-child td {{ border-bottom:none; }}
tr:nth-child(even) td {{ background:#F8FAFC; }}
.truncate-note {{ font-size:7pt; color:#94A3B8; margin-top:7px; }}

@page {{ size:letter; margin:{_MARGIN_TOP} 0 {_MARGIN_BOTTOM} 0; }}
{page_first_rule}
</style>
</head>
<body>

{cover_block}

<div class="content">
{sections}
</div>

{charts_js}
</body>
</html>'''


async def _render_html(browser, html: str, has_charts: bool, dest: str, header_footer: bool) -> None:
    page = await browser.new_page(viewport={"width": 1400, "height": 10000}, device_scale_factor=4)
    await page.set_content(html, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    if has_charts:
        try:
            await page.wait_for_function("window.chartsReady === true", timeout=15_000)
            await page.wait_for_timeout(1500)
        except Exception:
            await page.wait_for_timeout(2_000)
    kwargs: dict = {"path": dest, "format": "Letter", "print_background": True}
    if header_footer:
        kwargs.update({
            "display_header_footer": True,
            "header_template": _header_html(),
            "footer_template": _footer_html(),
            "margin": {"top": _MARGIN_TOP, "bottom": _MARGIN_BOTTOM, "left": "0", "right": "0"},
        })
    await page.pdf(**kwargs)
    await page.close()


@router.post("/export")
async def export_pdf(req: PDFRequest):
    from datetime import date
    from playwright.async_api import async_playwright
    from pypdf import PdfWriter, PdfReader

    date_str = date.today().strftime("%B %d, %Y")
    has_charts = any(_build_chartjs_config(w) for w in req.widgets)

    cover_html   = _build_html(req.title, req.tab_name, [], date_str, include_cover=True)
    content_html = _build_html(req.title, req.tab_name, req.widgets, date_str, include_cover=False)

    tmp_cover   = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_content = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_final   = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_cover.close(); tmp_content.close(); tmp_final.close()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            # Pass 1: cover page — no header/footer, no charts
            await _render_html(browser, cover_html, False, tmp_cover.name, header_footer=False)
            # Pass 2: content pages — header/footer, page counter starts at 1
            await _render_html(browser, content_html, has_charts, tmp_content.name, header_footer=True)
            await browser.close()

        writer = PdfWriter()
        writer.add_page(PdfReader(tmp_cover.name).pages[0])
        for p in PdfReader(tmp_content.name).pages:
            writer.add_page(p)
        with open(tmp_final.name, "wb") as f:
            writer.write(f)
    except Exception as e:
        for path in (tmp_cover.name, tmp_content.name, tmp_final.name):
            try: os.unlink(path)
            except OSError: pass
        raise e
    finally:
        for path in (tmp_cover.name, tmp_content.name):
            try: os.unlink(path)
            except OSError: pass

    return FileResponse(
        tmp_final.name,
        media_type="application/pdf",
        filename=f"{req.tab_name.replace(' ', '_')}_report.pdf",
        background=None,
    )
