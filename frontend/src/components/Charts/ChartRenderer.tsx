import {
  BarChart, Bar, LineChart, Line, ComposedChart, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import type { ChartType } from '../../types'
import { DataTable } from '../DataTable/DataTable'

const PALETTE = [
  '#2563EB', '#16A34A', '#D97706', '#DC2626', '#7C3AED',
  '#0891B2', '#DB2777', '#65A30D', '#EA580C', '#0D9488',
  '#9333EA', '#CA8A04', '#1D4ED8', '#15803D',
]

const MONEY_RE = /spend|dollar|amount|budget|fee|cost|ytd|capital|expense|salary/i
const COUNT_RE = /count|ftp|fte|hc|headcount|qty|quantity|rank|row_num|num_/i

function isMoney(key: string): boolean {
  return MONEY_RE.test(key) && !COUNT_RE.test(key)
}

// Axis ticks — abbreviated (900K, 10M)
function fmtMoney(val: number) {
  if (Math.abs(val) >= 1_000_000) return `$${(val / 1_000_000).toFixed(2)}M`
  if (Math.abs(val) >= 1_000) return `$${(val / 1_000).toFixed(2)}K`
  return `$${val.toFixed(2)}`
}

function fmtCount(val: number) {
  const abs = Math.abs(val)
  if (abs >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${(val / 1_000).toFixed(1)}K`
  return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2)
}

// Tooltip — full comma-separated numbers (900,000 / $10,000,000.00)
function fmtMoneyFull(val: number) {
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtCountFull(val: number) {
  return Number.isInteger(val)
    ? val.toLocaleString('en-US')
    : val.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function makeAxisFmt(keys: string[]): (val: unknown) => string {
  const money = keys.some((k) => isMoney(k))
  return (val) => {
    if (typeof val !== 'number') return String(val ?? '')
    return money ? fmtMoney(val) : fmtCount(val)
  }
}

function tooltipFmt(v: number, name: unknown): string {
  const key = String(name ?? '')
  return isMoney(key) ? fmtMoneyFull(v) : fmtCountFull(v)
}

interface Props {
  chart_type: ChartType
  data: Record<string, unknown>[]
  x_axis?: string
  y_axis: string[]
  color_field?: string
  stacked?: boolean
  dual_axis?: boolean
  secondary_y?: string
  height?: number
}

function pivotByColorField(
  data: Record<string, unknown>[],
  x_axis: string,
  y_key: string,
  color_field: string
): { pivoted: Record<string, unknown>[]; categories: string[] } {
  const categories = [...new Set(data.map((r) => String(r[color_field] ?? 'Unknown')))]
  const byX: Record<string, Record<string, unknown>> = {}
  for (const row of data) {
    const xv = String(row[x_axis] ?? '')
    if (!byX[xv]) byX[xv] = { [x_axis]: xv }
    byX[xv][String(row[color_field] ?? 'Unknown')] = row[y_key]
  }
  return { pivoted: Object.values(byX), categories }
}

export function ChartRenderer({ chart_type, data, x_axis, y_axis, color_field, stacked, dual_axis, secondary_y, height = 220 }: Props) {
  if (!data?.length) return <p className="text-sm text-gray-400 text-center py-8">No data</p>

  // Robustly resolve keys — scan all rows so a null in data[0] doesn't break inference
  const allCols = Object.keys(data[0])
  const numericCols = allCols.filter(k => data.some(r => typeof r[k] === 'number'))
  const stringCols  = allCols.filter(k => data.some(r => typeof r[k] === 'string'))

  // Prefer x_axis if it points to a non-numeric column; fall back to first string col
  const xKey = (x_axis && allCols.includes(x_axis) && !numericCols.includes(x_axis))
    ? x_axis
    : (stringCols[0] ?? allCols[0])
  const validY = y_axis.filter(k => allCols.includes(k) && data.some(r => typeof r[k] === 'number'))
  const yKeys = validY.length ? validY : numericCols.filter(k => k !== xKey).slice(0, 4)
  const primaryKeys = yKeys.filter((k) => k !== secondary_y)
  const axisFmt = makeAxisFmt(primaryKeys)

  // ── KPI ──────────────────────────────────────────────────────────────────
  if (chart_type === 'kpi') {
    const row = data[0]
    return (
      <div className="flex flex-wrap gap-4 py-4 justify-center">
        {Object.entries(row).map(([k, v]) => {
          const formatted = typeof v === 'number'
            ? (isMoney(k) ? fmtMoneyFull(v) : fmtCountFull(v))
            : String(v)
          return (
            <div key={k} className="text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{k.replace(/_/g, ' ')}</p>
              <p className="text-3xl font-bold text-gray-900">{formatted}</p>
            </div>
          )
        })}
      </div>
    )
  }

  // ── TABLE ─────────────────────────────────────────────────────────────────
  if (chart_type === 'table') return <DataTable data={data} />

  // ── DONUT / PIE ───────────────────────────────────────────────────────────
  if (chart_type === 'donut' || chart_type === 'pie') {
    const valKey = yKeys[0] || numericCols[0] || ''
    const labelKey = xKey
    return (
      <ResponsiveContainer width="100%" height={height + 70}>
        <PieChart margin={{ top: 35, right: 55, bottom: 20, left: 55 }}>
          <Pie
            data={data}
            dataKey={valKey}
            nameKey={labelKey}
            cx="50%"
            cy="40%"
            innerRadius={chart_type === 'donut' ? '40%' : 0}
            outerRadius="100%"
            label={({ cx, cy, midAngle, outerRadius, name, percent }: { cx: number; cy: number; midAngle: number; outerRadius: number; name: string; percent: number }) => {
              const RAD = Math.PI / 180
              const r = outerRadius + 14
              const x = cx + r * Math.cos(-midAngle * RAD)
              const y = cy + r * Math.sin(-midAngle * RAD)
              return (
                <text x={x} y={y} fill="#555" fontSize={10} textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central">
                  {`${name} (${(percent * 100).toFixed(2)}%)`}
                </text>
              )
            }}
            labelLine={true}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number) => isMoney(valKey) ? fmtMoneyFull(v) : fmtCountFull(v)} contentStyle={{ fontSize: '10px' }} />
          <Legend wrapperStyle={{ fontSize: '10px', paddingTop: '12px' }} />
        </PieChart>
      </ResponsiveContainer>
    )
  }

  // ── HORIZONTAL BAR ────────────────────────────────────────────────────────
  if (chart_type === 'horizontal_bar') {
    const valKey = yKeys[0] || numericCols[0] || ''
    const BAR_SLOT_MAX = 72
    const chartH = Math.min(
      Math.max(height, data.length * 32),
      data.length * BAR_SLOT_MAX
    )
    const barSz = Math.round((chartH / data.length) * 0.67)
    return (
      <ResponsiveContainer width="100%" height={chartH}>
        <BarChart layout="vertical" data={data} margin={{ left: 16, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickFormatter={axisFmt} tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey={xKey} tick={{ fontSize: 11 }} width={60} />
          <Tooltip formatter={tooltipFmt} contentStyle={{ fontSize: '10px' }} />
          <Bar dataKey={valKey} fill={PALETTE[0]} radius={[0, 3, 3, 0]} barSize={barSz} />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  // ── LINE ──────────────────────────────────────────────────────────────────
  if (chart_type === 'line') {
    // Pivot if color_field present
    let renderData = data
    let keys = yKeys
    if (color_field && color_field in data[0]) {
      const { pivoted, categories } = pivotByColorField(data, xKey, yKeys[0], color_field)
      renderData = pivoted
      keys = categories
    }
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={renderData} margin={{ top: 4, right: 16, bottom: 4, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={axisFmt} tick={{ fontSize: 11 }} width={64} />
          <Tooltip formatter={tooltipFmt} contentStyle={{ fontSize: '10px' }} />
          <Legend wrapperStyle={{ fontSize: '10px' }} />
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={{ r: 3 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  // ── BAR / STACKED_BAR ────────────────────────────────────────────────────
  if (chart_type === 'bar' || chart_type === 'stacked_bar') {
    let renderData = data
    let keys = yKeys
    if (color_field && data[0][color_field] !== undefined) {
      const { pivoted, categories } = pivotByColorField(data, xKey, yKeys[0] || Object.keys(data[0]).find(k => typeof data[0][k] === 'number') || '', color_field)
      renderData = pivoted
      keys = categories
    }
    const isStacked = stacked || chart_type === 'stacked_bar'
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={renderData} margin={{ top: 4, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} angle={-25} textAnchor="end" interval={0} />
          <YAxis tickFormatter={axisFmt} tick={{ fontSize: 11 }} />
          <Tooltip formatter={tooltipFmt} contentStyle={{ fontSize: '10px' }} />
          <Legend wrapperStyle={{ fontSize: '10px' }} />
          {keys.map((k, i) => (
            <Bar key={k} dataKey={k} fill={PALETTE[i % PALETTE.length]} stackId={isStacked ? 'stack' : undefined} radius={isStacked ? undefined : [3, 3, 0, 0]} barSize={20} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  }

  // ── COMBO (bar + line) ────────────────────────────────────────────────────
  if (chart_type === 'combo') {
    const barKeys = yKeys.filter((k) => k !== secondary_y)
    const lineKey = secondary_y || yKeys[yKeys.length - 1]
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 32, bottom: 24, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} angle={-25} textAnchor="end" interval={0} />
          <YAxis yAxisId="left" tickFormatter={axisFmt} tick={{ fontSize: 11 }} />
          {dual_axis && <YAxis yAxisId="right" orientation="right" tickFormatter={fmtCount} tick={{ fontSize: 11 }} />}
          <Tooltip formatter={tooltipFmt} contentStyle={{ fontSize: '10px' }} />
          <Legend wrapperStyle={{ fontSize: '10px' }} />
          {barKeys.map((k, i) => (
            <Bar key={k} yAxisId="left" dataKey={k} fill={PALETTE[i % PALETTE.length]} stackId={stacked ? 'stack' : undefined} />
          ))}
          {lineKey && (
            <Line
              yAxisId={dual_axis ? 'right' : 'left'}
              type="monotone"
              dataKey={lineKey}
              stroke={PALETTE[barKeys.length % PALETTE.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    )
  }

  // Fallback
  return <DataTable data={data} />
}
