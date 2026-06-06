import { useState } from 'react'
import { Download } from 'lucide-react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

type Status    = 'in-band' | 'below-target' | 'above-target' | 'under-plan' | 'over-plan'
type DrillView = 'category' | 'use-case' | 'vendor'
type Period    = 'YTD' | 'Q1' | 'Q2' | 'Q3' | 'Q4'

interface TileMeta {
  id: string; label: string
  rangeMin: number; rangeMax: number
  targetMin: number; targetMax: number
  rangeUnit: string; targetLabel: string
  isSpendTile?: boolean
}
interface TileVal {
  value: string; delta: string; deltaLabel: string; current: number
  status: Status; statusLabel: string
  planCurrent?: number  // range-bar plan dot for non-spend tiles
  planLabel?: string    // e.g. "Plan: 5.0%"
  planValue?: number    // spend tile: plan budget cap
}
interface BarItem     { label: string; amount: number; plan?: number }
interface UseCaseItem { rank: string; name: string; kpi: string; amount: number; plan?: number }
interface DrillData   { byCategory: BarItem[]; byUseCase: UseCaseItem[]; byVendor: BarItem[] }

// ── Static tile metadata (never changes with period) ──────────────────────────

const TILE_META: TileMeta[] = [
  { id: 'revenue',    label: 'Revenue Growth',  rangeMin: 0, rangeMax: 10, targetMin: 3,  targetMax: 7,  rangeUnit: '%', targetLabel: 'target band 3–7%'   },
  { id: 'nps',        label: 'NPS Improvement', rangeMin: 0, rangeMax: 6,  targetMin: 2,  targetMax: 4,  rangeUnit: '',  targetLabel: 'target band 2–4'    },
  { id: 'efficiency', label: 'Efficiency Gain', rangeMin: 0, rangeMax: 50, targetMin: 30, targetMax: 40, rangeUnit: '%', targetLabel: 'target band 30–40%' },
  { id: 'ai-cost',    label: 'AI Cost',         rangeMin: 0, rangeMax: 60, targetMin: 0,  targetMax: 45, rangeUnit: 'M', targetLabel: '', isSpendTile: true },
]

// ── Per-period tile values ────────────────────────────────────────────────────

const PERIOD_TILES: Record<Period, TileVal[]> = {
  YTD: [
    { value: '4.6%',   delta: '+0.4',    deltaLabel: 'vs Q3',    current: 4.6,  status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 5.0, planLabel: 'Plan 5.0%'    },
    { value: '2.7pts', delta: '+0.3',    deltaLabel: 'vs Q3',    current: 2.7,  status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 3.0, planLabel: 'Plan 3.0pts'  },
    { value: '27%',    delta: '+5',      deltaLabel: 'vs Q3',    current: 27,   status: 'below-target', statusLabel: 'BELOW TARGET', planCurrent: 33,  planLabel: 'Plan 33%'     },
    { value: '$42.3M', delta: '−$2.7M',  deltaLabel: 'vs plan',  current: 42.3, status: 'under-plan',   statusLabel: 'UNDER PLAN',   planValue: 45 },
  ],
  Q1: [
    { value: '3.8%',   delta: '+0.2',   deltaLabel: 'vs Q4\'25', current: 3.8, status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 4.0, planLabel: 'Plan 4.0%'   },
    { value: '2.4pts', delta: '+0.1',   deltaLabel: 'vs Q4\'25', current: 2.4, status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 2.5, planLabel: 'Plan 2.5pts' },
    { value: '18%',    delta: '+2',     deltaLabel: 'vs Q4\'25', current: 18,  status: 'below-target', statusLabel: 'BELOW TARGET', planCurrent: 25,  planLabel: 'Plan 25%'    },
    { value: '$9.8M',  delta: '−$1.5M', deltaLabel: 'vs plan',   current: 9.8, status: 'under-plan',   statusLabel: 'UNDER PLAN',   planValue: 11.25 },
  ],
  Q2: [
    { value: '5.1%',   delta: '+1.3',   deltaLabel: 'vs Q1', current: 5.1,  status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 5.0, planLabel: 'Plan 5.0%'   },
    { value: '2.8pts', delta: '+0.4',   deltaLabel: 'vs Q1', current: 2.8,  status: 'in-band',      statusLabel: 'IN BAND',      planCurrent: 3.0, planLabel: 'Plan 3.0pts' },
    { value: '29%',    delta: '+11',    deltaLabel: 'vs Q1', current: 29,   status: 'below-target', statusLabel: 'BELOW TARGET', planCurrent: 32,  planLabel: 'Plan 32%'    },
    { value: '$11.2M', delta: '−$0.1M', deltaLabel: 'vs plan', current: 11.2, status: 'under-plan',  statusLabel: 'UNDER PLAN',  planValue: 11.25 },
  ],
  Q3: [
    { value: '4.9%',   delta: '−0.2',   deltaLabel: 'vs Q2', current: 4.9,  status: 'in-band',    statusLabel: 'IN BAND',   planCurrent: 5.0, planLabel: 'Plan 5.0%'   },
    { value: '2.9pts', delta: '+0.1',   deltaLabel: 'vs Q2', current: 2.9,  status: 'in-band',    statusLabel: 'IN BAND',   planCurrent: 3.0, planLabel: 'Plan 3.0pts' },
    { value: '31%',    delta: '+2',     deltaLabel: 'vs Q2', current: 31,   status: 'in-band',    statusLabel: 'IN BAND',   planCurrent: 32,  planLabel: 'Plan 32%'    },
    { value: '$13.8M', delta: '+$2.6M', deltaLabel: 'vs plan', current: 13.8, status: 'over-plan', statusLabel: 'OVER PLAN', planValue: 11.25 },
  ],
  Q4: [
    { value: '5.2%',   delta: '+0.3',    deltaLabel: 'vs Q3', current: 5.2, status: 'in-band',    statusLabel: 'IN BAND',      planCurrent: 5.0, planLabel: 'Plan 5.0%'   },
    { value: '3.1pts', delta: '+0.2',    deltaLabel: 'vs Q3', current: 3.1, status: 'in-band',    statusLabel: 'IN BAND',      planCurrent: 3.0, planLabel: 'Plan 3.0pts' },
    { value: '35%',    delta: '+4',      deltaLabel: 'vs Q3', current: 35,  status: 'in-band',    statusLabel: 'IN BAND',      planCurrent: 35,  planLabel: 'Plan 35%'    },
    { value: '$7.5M',  delta: '−$3.75M', deltaLabel: 'vs plan', current: 7.5, status: 'under-plan', statusLabel: 'UNDER PLAN', planValue: 11.25 },
  ],
}

// ── Per-period drill data (with plan for VS PLAN mode) ────────────────────────

const PERIOD_DRILL: Record<Period, DrillData> = {
  YTD: {
    byCategory: [
      { label: 'Foundation model inference', amount: 18.2, plan: 20.0 },
      { label: 'Cloud compute & storage',    amount: 11.4, plan: 12.0 },
      { label: 'Data labeling & ops',        amount: 5.6,  plan: 6.0  },
      { label: 'Platform & MLOps tooling',   amount: 4.1,  plan: 4.5  },
      { label: 'Talent allocation',          amount: 3.0,  plan: 2.5  },
    ],
    byUseCase: [
      { rank: '01', name: 'Personalized Search & Discovery',  kpi: 'REVENUE',    amount: 6.8, plan: 7.5 },
      { rank: '02', name: 'Demand Forecast v3',               kpi: 'EFFICIENCY', amount: 4.8, plan: 5.0 },
      { rank: '03', name: 'Dynamic Markdown Optimization',    kpi: 'REVENUE',    amount: 4.2, plan: 4.5 },
      { rank: '04', name: 'Warehouse Slotting AI',            kpi: 'EFFICIENCY', amount: 3.6, plan: 4.0 },
      { rank: '05', name: 'Conversational Returns Assistant', kpi: 'NPS',        amount: 3.2, plan: 3.5 },
      { rank: '06', name: 'Chat Triage & Routing',            kpi: 'NPS',        amount: 2.4, plan: 2.5 },
    ],
    byVendor: [
      { label: 'Google Cloud (Vertex AI)', amount: 14.1, plan: 15.0 },
      { label: 'OpenAI / Azure OpenAI',   amount: 9.7,  plan: 10.5 },
      { label: 'AWS Bedrock',             amount: 7.5,  plan: 8.0  },
      { label: 'Scale AI (labeling)',     amount: 5.6,  plan: 6.0  },
      { label: 'Databricks',             amount: 3.2,  plan: 3.5  },
      { label: 'Other vendors',          amount: 2.2,  plan: 2.0  },
    ],
  },
  Q1: {
    byCategory: [
      { label: 'Foundation model inference', amount: 4.2, plan: 5.0  },
      { label: 'Cloud compute & storage',    amount: 2.5, plan: 3.0  },
      { label: 'Data labeling & ops',        amount: 1.3, plan: 1.5  },
      { label: 'Platform & MLOps tooling',   amount: 1.1, plan: 1.1  },
      { label: 'Talent allocation',          amount: 0.7, plan: 0.65 },
    ],
    byUseCase: [
      { rank: '01', name: 'Personalized Search & Discovery',  kpi: 'REVENUE',    amount: 1.5, plan: 1.9 },
      { rank: '02', name: 'Demand Forecast v3',               kpi: 'EFFICIENCY', amount: 1.1, plan: 1.2 },
      { rank: '03', name: 'Dynamic Markdown Optimization',    kpi: 'REVENUE',    amount: 0.9, plan: 1.1 },
      { rank: '04', name: 'Warehouse Slotting AI',            kpi: 'EFFICIENCY', amount: 0.8, plan: 1.0 },
      { rank: '05', name: 'Conversational Returns Assistant', kpi: 'NPS',        amount: 0.7, plan: 0.9 },
    ],
    byVendor: [
      { label: 'Google Cloud (Vertex AI)', amount: 3.2, plan: 3.8 },
      { label: 'OpenAI / Azure OpenAI',   amount: 2.1, plan: 2.6 },
      { label: 'AWS Bedrock',             amount: 1.8, plan: 2.0 },
      { label: 'Scale AI (labeling)',     amount: 1.3, plan: 1.5 },
      { label: 'Databricks',             amount: 0.8, plan: 0.9 },
      { label: 'Other vendors',          amount: 0.6, plan: 0.5 },
    ],
  },
  Q2: {
    byCategory: [
      { label: 'Foundation model inference', amount: 4.9, plan: 5.0  },
      { label: 'Cloud compute & storage',    amount: 2.8, plan: 3.0  },
      { label: 'Data labeling & ops',        amount: 1.4, plan: 1.5  },
      { label: 'Platform & MLOps tooling',   amount: 1.2, plan: 1.1  },
      { label: 'Talent allocation',          amount: 0.9, plan: 0.65 },
    ],
    byUseCase: [
      { rank: '01', name: 'Personalized Search & Discovery',  kpi: 'REVENUE',    amount: 1.8, plan: 1.9 },
      { rank: '02', name: 'Demand Forecast v3',               kpi: 'EFFICIENCY', amount: 1.3, plan: 1.2 },
      { rank: '03', name: 'Dynamic Markdown Optimization',    kpi: 'REVENUE',    amount: 1.1, plan: 1.1 },
      { rank: '04', name: 'Warehouse Slotting AI',            kpi: 'EFFICIENCY', amount: 1.0, plan: 1.0 },
      { rank: '05', name: 'Conversational Returns Assistant', kpi: 'NPS',        amount: 0.9, plan: 0.9 },
      { rank: '06', name: 'Chat Triage & Routing',            kpi: 'NPS',        amount: 0.7, plan: 0.6 },
    ],
    byVendor: [
      { label: 'Google Cloud (Vertex AI)', amount: 3.7, plan: 3.8 },
      { label: 'OpenAI / Azure OpenAI',   amount: 2.5, plan: 2.6 },
      { label: 'AWS Bedrock',             amount: 2.1, plan: 2.0 },
      { label: 'Scale AI (labeling)',     amount: 1.4, plan: 1.5 },
      { label: 'Databricks',             amount: 0.9, plan: 0.9 },
      { label: 'Other vendors',          amount: 0.6, plan: 0.5 },
    ],
  },
  Q3: {
    byCategory: [
      { label: 'Foundation model inference', amount: 5.9, plan: 5.0  },
      { label: 'Cloud compute & storage',    amount: 3.5, plan: 3.0  },
      { label: 'Data labeling & ops',        amount: 2.0, plan: 1.5  },
      { label: 'Platform & MLOps tooling',   amount: 1.5, plan: 1.1  },
      { label: 'Talent allocation',          amount: 0.9, plan: 0.65 },
    ],
    byUseCase: [
      { rank: '01', name: 'Personalized Search & Discovery',  kpi: 'REVENUE',    amount: 2.2, plan: 1.9 },
      { rank: '02', name: 'Demand Forecast v3',               kpi: 'EFFICIENCY', amount: 1.6, plan: 1.2 },
      { rank: '03', name: 'Dynamic Markdown Optimization',    kpi: 'REVENUE',    amount: 1.3, plan: 1.1 },
      { rank: '04', name: 'Warehouse Slotting AI',            kpi: 'EFFICIENCY', amount: 1.1, plan: 1.0 },
      { rank: '05', name: 'Conversational Returns Assistant', kpi: 'NPS',        amount: 1.0, plan: 0.9 },
      { rank: '06', name: 'Chat Triage & Routing',            kpi: 'NPS',        amount: 0.8, plan: 0.6 },
    ],
    byVendor: [
      { label: 'Google Cloud (Vertex AI)', amount: 4.5, plan: 3.8 },
      { label: 'OpenAI / Azure OpenAI',   amount: 3.2, plan: 2.6 },
      { label: 'AWS Bedrock',             amount: 2.4, plan: 2.0 },
      { label: 'Scale AI (labeling)',     amount: 1.8, plan: 1.5 },
      { label: 'Databricks',             amount: 1.1, plan: 0.9 },
      { label: 'Other vendors',          amount: 0.8, plan: 0.5 },
    ],
  },
  Q4: {
    byCategory: [
      { label: 'Foundation model inference', amount: 3.2, plan: 5.0  },
      { label: 'Cloud compute & storage',    amount: 1.9, plan: 3.0  },
      { label: 'Data labeling & ops',        amount: 0.9, plan: 1.5  },
      { label: 'Platform & MLOps tooling',   amount: 0.9, plan: 1.1  },
      { label: 'Talent allocation',          amount: 0.6, plan: 0.65 },
    ],
    byUseCase: [
      { rank: '01', name: 'Personalized Search & Discovery',  kpi: 'REVENUE',    amount: 1.3, plan: 1.9 },
      { rank: '02', name: 'Dynamic Markdown Optimization',    kpi: 'REVENUE',    amount: 0.9, plan: 1.1 },
      { rank: '03', name: 'Demand Forecast v3',               kpi: 'EFFICIENCY', amount: 0.8, plan: 1.2 },
      { rank: '04', name: 'Warehouse Slotting AI',            kpi: 'EFFICIENCY', amount: 0.7, plan: 1.0 },
      { rank: '05', name: 'Conversational Returns Assistant', kpi: 'NPS',        amount: 0.6, plan: 0.9 },
    ],
    byVendor: [
      { label: 'Google Cloud (Vertex AI)', amount: 2.5, plan: 3.8 },
      { label: 'OpenAI / Azure OpenAI',   amount: 1.6, plan: 2.6 },
      { label: 'AWS Bedrock',             amount: 1.3, plan: 2.0 },
      { label: 'Scale AI (labeling)',     amount: 1.0, plan: 1.5 },
      { label: 'Databricks',             amount: 0.6, plan: 0.9 },
      { label: 'Other vendors',          amount: 0.5, plan: 0.5 },
    ],
  },
}

const DRILL_VIEWS: { key: DrillView; label: string }[] = [
  { key: 'category', label: 'By Category' },
  { key: 'use-case', label: 'By Use Case' },
  { key: 'vendor',   label: 'By Vendor'   },
]

// ── Design tokens ─────────────────────────────────────────────────────────────

const STATUS: Record<Status, { strip: string; dot: string; badgeText: string; badgeBg: string; badgeBorder: string }> = {
  'in-band':      { strip: 'bg-emerald-400', dot: 'bg-emerald-400', badgeText: 'text-emerald-700', badgeBg: 'bg-emerald-50',  badgeBorder: 'border-emerald-200' },
  'below-target': { strip: 'bg-amber-400',   dot: 'bg-amber-400',   badgeText: 'text-amber-700',   badgeBg: 'bg-amber-50',    badgeBorder: 'border-amber-200'   },
  'above-target': { strip: 'bg-emerald-400', dot: 'bg-emerald-400', badgeText: 'text-emerald-700', badgeBg: 'bg-emerald-50',  badgeBorder: 'border-emerald-200' },
  'under-plan':   { strip: 'bg-sky-400',     dot: 'bg-sky-400',     badgeText: 'text-sky-700',     badgeBg: 'bg-sky-50',      badgeBorder: 'border-sky-200'     },
  'over-plan':    { strip: 'bg-rose-400',    dot: 'bg-rose-400',    badgeText: 'text-rose-700',    badgeBg: 'bg-rose-50',     badgeBorder: 'border-rose-200'    },
}

const KPI_TAG: Record<string, string> = {
  REVENUE:    'bg-blue-50   text-blue-700   ring-1 ring-inset ring-blue-600/20',
  EFFICIENCY: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20',
  NPS:        'bg-purple-50 text-purple-700  ring-1 ring-inset ring-purple-600/20',
}

function asPct(val: number, min: number, max: number) {
  return `${Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100)).toFixed(2)}%`
}
function kpiTag(kpi: string) { return KPI_TAG[kpi] ?? 'bg-gray-100 text-gray-600' }

// ── Range bar ─────────────────────────────────────────────────────────────────

function RangeBar({ meta, val, vsPlan }: { meta: TileMeta; val: TileVal; vsPlan: boolean }) {
  const { rangeMin, rangeMax, targetMin, targetMax, rangeUnit, targetLabel, isSpendTile } = meta
  const { current, planValue, planCurrent } = val

  if (isSpendTile) {
    const budget  = planValue ?? 45
    const fillW   = asPct(current, rangeMin, rangeMax)
    const planL   = asPct(budget,  rangeMin, rangeMax)
    return (
      <div className="mt-5">
        <div className="relative h-2 bg-gray-100 rounded-full w-full">
          <div className="absolute inset-y-0 left-0 bg-gray-800 rounded-full transition-all duration-700" style={{ width: fillW }} />
          <div className="absolute top-1/2 -translate-y-1/2 w-px h-5 bg-amber-400" style={{ left: planL }} />
        </div>
        <div className="relative flex justify-between mt-2">
          <span className="text-[11px] text-gray-400">$0M</span>
          <span className="absolute text-[11px] font-semibold text-amber-600 -translate-x-1/2 whitespace-nowrap" style={{ left: planL }}>
            plan ${budget}M
          </span>
          <span className="text-[11px] text-gray-400">${rangeMax}M</span>
        </div>
      </div>
    )
  }

  const targetL  = asPct(targetMin, rangeMin, rangeMax)
  const targetW  = `${((targetMax - targetMin) / (rangeMax - rangeMin)) * 100}%`
  const currentL = asPct(current,   rangeMin, rangeMax)
  const planL    = planCurrent !== undefined ? asPct(planCurrent, rangeMin, rangeMax) : null

  return (
    <div className="mt-5">
      <div className="relative h-2 bg-gray-100 rounded-full w-full">
        <div className="absolute inset-y-0 bg-gray-300 rounded-full" style={{ left: targetL, width: targetW }} />
        {/* Plan dot — VS PLAN mode */}
        {vsPlan && planL && (
          <div
            className="absolute top-1/2 w-3.5 h-3.5 bg-sky-400 rounded-full border-2 border-white shadow ring-1 ring-sky-200"
            style={{ left: planL, transform: 'translate(-50%, -50%)' }}
          />
        )}
        {/* Actual dot */}
        <div
          className="absolute top-1/2 w-4 h-4 bg-gray-900 rounded-full border-2 border-white shadow-md"
          style={{ left: currentL, transform: 'translate(-50%, -50%)' }}
        />
      </div>
      <div className="flex justify-between mt-2">
        <span className="text-[11px] text-gray-400">{rangeMin}{rangeUnit}</span>
        <span className="text-[11px] font-medium text-gray-500">{targetLabel}</span>
        <span className="text-[11px] text-gray-400">{rangeMax}{rangeUnit}</span>
      </div>
    </div>
  )
}

// ── KPI card (display only — not clickable) ───────────────────────────────────

function KpiCard({ meta, val, period, vsPlan }: {
  meta: TileMeta; val: TileVal; period: Period; vsPlan: boolean
}) {
  const t = STATUS[val.status]
  return (
    <div className="relative flex flex-col rounded-2xl overflow-hidden bg-white shadow-sm ring-1 ring-gray-100 hover:shadow-lg transition-shadow duration-200">
      <div className={clsx('absolute left-0 top-0 bottom-0 w-1', t.strip)} />
      <div className="pl-6 pr-5 pt-5 pb-5 flex flex-col flex-1">

        {/* Header */}
        <div className="flex justify-between items-center">
          <span className="text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase">{meta.label}</span>
          <span className={clsx('text-[9px] font-bold px-2 py-0.5 rounded-full border tracking-wide', t.badgeBg, t.badgeBorder, t.badgeText)}>
            {period}
          </span>
        </div>

        {/* Value + delta */}
        <div className="mt-3">
          <div className="text-[2.6rem] font-black text-gray-900 leading-none tracking-tight">{val.value}</div>
          <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
            <span className="text-sm font-bold text-gray-700">{val.delta}</span>
            <span className="text-xs text-gray-400">{val.deltaLabel}</span>
          </div>
        </div>

        {/* Range bar */}
        <RangeBar meta={meta} val={val} vsPlan={vsPlan} />

        {/* Status badge + plan label on same row — no height shift when VS PLAN toggles */}
        <div className="mt-4 pt-3.5 border-t border-gray-50 flex items-center justify-between gap-2">
          <span className={clsx(
            'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wide border',
            t.badgeBg, t.badgeBorder, t.badgeText,
          )}>
            <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', t.dot)} />
            {val.statusLabel}
          </span>
          {vsPlan && val.planLabel && !meta.isSpendTile && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold text-sky-600 whitespace-nowrap">
              <span className="w-2 h-2 rounded-full bg-sky-400 flex-shrink-0" />
              {val.planLabel}
            </span>
          )}
        </div>

      </div>
    </div>
  )
}

// ── Left widget — bar chart ───────────────────────────────────────────────────

function BarChartWidget({ drill, view, vsPlan, costLabel }: {
  drill: DrillData; view: DrillView; vsPlan: boolean; costLabel: string
}) {
  const items: BarItem[] =
    view === 'category' ? drill.byCategory :
    view === 'vendor'   ? drill.byVendor   :
    drill.byUseCase.map(u => ({ label: u.name, amount: u.amount, plan: u.plan }))

  const maxBar  = Math.max(...items.map(i => Math.max(i.amount, i.plan ?? 0)))
  const total   = items.reduce((s, i) => s + i.amount, 0)

  const heading =
    view === 'category' ? 'Spend by category' :
    view === 'vendor'   ? 'Spend by vendor'   :
    'Spend by initiative'

  return (
    <div className="col-span-2 bg-white rounded-2xl shadow-sm ring-1 ring-gray-100 p-6 flex flex-col">
      <div className="flex items-start justify-between mb-6">
        <div>
          <p className="text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase">{heading}</p>
          <p className="text-sm font-black text-gray-900 mt-0.5">${total.toFixed(1)}M total</p>
        </div>
        <p className="text-[10px] text-gray-400 font-medium text-right leading-relaxed max-w-[120px]">{costLabel}</p>
      </div>

      <div className="space-y-5 flex-1">
        {items.map((item, i) => {
          const pctOfTotal = ((item.amount / total) * 100).toFixed(0)
          const actualW    = `${(item.amount / maxBar) * 100}%`
          const planW      = item.plan ? `${(item.plan / maxBar) * 100}%` : '0%'
          const isOver     = item.plan !== undefined && item.amount > item.plan
          return (
            <div key={item.label}>
              <div className="flex justify-between items-baseline mb-2">
                <span className="text-sm font-semibold text-gray-700 leading-tight pr-4">{item.label}</span>
                <div className="flex items-center gap-2 shrink-0">
                  {vsPlan && item.plan && (
                    <span className={clsx('text-[11px] font-semibold', isOver ? 'text-rose-500' : 'text-sky-500')}>
                      Plan ${item.plan}M
                    </span>
                  )}
                  <span className="text-sm font-black text-gray-900 tabular-nums">${item.amount}M</span>
                </div>
              </div>
              <div className="relative h-2 bg-gray-100 rounded-full overflow-hidden">
                {/* Plan bar behind */}
                {vsPlan && item.plan && (
                  <div
                    className="absolute inset-y-0 left-0 bg-sky-100 rounded-full"
                    style={{ width: planW, transition: `width 0.5s ease ${i * 60}ms` }}
                  />
                )}
                {/* Actual bar */}
                <div
                  className={clsx('absolute inset-y-0 left-0 rounded-full', isOver && vsPlan ? 'bg-rose-500' : 'bg-gray-800')}
                  style={{ width: actualW, transition: `width 0.5s cubic-bezier(.4,0,.2,1) ${i * 60}ms` }}
                />
              </div>
              <p className="mt-1 text-[10px] text-gray-400 font-medium">{pctOfTotal}% of total</p>
            </div>
          )
        })}
      </div>

      {vsPlan && (
        <div className="mt-5 pt-4 border-t border-gray-50 flex items-center gap-4 text-[11px] font-semibold">
          <span className="flex items-center gap-1.5"><span className="w-3 h-1.5 rounded-full bg-gray-800 inline-block" /> Actual</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-1.5 rounded-full bg-sky-200 inline-block" /> Plan</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-1.5 rounded-full bg-rose-400 inline-block" /> Over plan</span>
        </div>
      )}
    </div>
  )
}

// ── Right widget — use case table ─────────────────────────────────────────────

function UseCaseWidget({ drill, vsPlan }: { drill: DrillData; vsPlan: boolean }) {
  const items    = drill.byUseCase
  const maxAmt   = Math.max(...items.map(u => Math.max(u.amount, u.plan ?? 0)))

  return (
    <div className="col-span-3 bg-white rounded-2xl shadow-sm ring-1 ring-gray-100 p-6 flex flex-col">
      <div className="mb-6">
        <p className="text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase">
          Top {items.length} use cases by spend
        </p>
      </div>

      {/* Header row */}
      <div className="grid pb-2.5 border-b border-gray-100 mb-1" style={{ gridTemplateColumns: vsPlan ? 'repeat(13, minmax(0,1fr))' : 'repeat(12, minmax(0,1fr))' }}>
        <div className="col-span-1 text-[10px] font-bold tracking-wider text-gray-400">#</div>
        <div className="col-span-5 text-[10px] font-bold tracking-wider text-gray-400">Use case</div>
        <div className="col-span-2 text-[10px] font-bold tracking-wider text-gray-400">KPI</div>
        <div className="col-span-2 text-[10px] font-bold tracking-wider text-gray-400">Spend</div>
        <div className="col-span-2 text-[10px] font-bold tracking-wider text-gray-400 text-right">$M</div>
        {vsPlan && <div className="col-span-1 text-[10px] font-bold tracking-wider text-gray-400 text-right">Plan</div>}
      </div>

      <div className="flex-1">
        {items.map((uc, i) => {
          const actualW = `${(uc.amount / maxAmt) * 100}%`
          const planW   = uc.plan ? `${(uc.plan / maxAmt) * 100}%` : '0%'
          const isOver  = uc.plan !== undefined && uc.amount > uc.plan
          return (
            <div
              key={uc.rank}
              className={clsx(
                'grid items-center py-3 rounded-xl -mx-2 px-2 transition-colors hover:bg-gray-50',
                i < items.length - 1 && 'border-b border-gray-50',
              )}
              style={{ gridTemplateColumns: vsPlan ? 'repeat(13, minmax(0,1fr))' : 'repeat(12, minmax(0,1fr))' }}
            >
              <div className="col-span-1">
                <span className="text-xs font-black font-mono text-gray-300">{uc.rank}</span>
              </div>
              <div className="col-span-5 pr-2">
                <span className="text-sm font-semibold text-gray-800 leading-snug">{uc.name}</span>
              </div>
              <div className="col-span-2">
                <span className={clsx('text-[10px] font-bold px-2 py-0.5 rounded-full', kpiTag(uc.kpi))}>
                  {uc.kpi}
                </span>
              </div>
              <div className="col-span-2 pr-2">
                <div className="relative h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  {vsPlan && uc.plan && (
                    <div className="absolute inset-y-0 left-0 bg-sky-100 rounded-full" style={{ width: planW }} />
                  )}
                  <div
                    className={clsx('absolute inset-y-0 left-0 rounded-full', isOver && vsPlan ? 'bg-rose-500' : 'bg-gray-800')}
                    style={{ width: actualW, transition: `width 0.5s cubic-bezier(.4,0,.2,1) ${i * 60}ms` }}
                  />
                </div>
              </div>
              <div className="col-span-2 text-right">
                <span className={clsx('text-sm font-black tabular-nums', isOver && vsPlan ? 'text-rose-600' : 'text-gray-900')}>
                  ${uc.amount}M
                </span>
              </div>
              {vsPlan && (
                <div className="col-span-1 text-right">
                  <span className="text-[11px] font-semibold text-sky-500 tabular-nums">${uc.plan}M</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export function AIAmbitionTab() {
  const [period,   setPeriod]   = useState<Period>('YTD')
  const [vsPlan,   setVsPlan]   = useState(false)
  const [drillView, setDrillView] = useState<DrillView>('category')

  const tileVals = PERIOD_TILES[period]
  const drill    = PERIOD_DRILL[period]
  const costVal  = tileVals[3].value   // AI Cost value for the current period
  const costLabel = `Where the ${costVal} is going`

  return (
    <div className="flex flex-col gap-5 p-6 bg-gray-50/60 min-h-full">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-gray-900 tracking-tight">AI Ambition</h1>
          <p className="text-xs text-gray-400 mt-0.5 font-medium tracking-wide">FY26 · AI investment performance tracker</p>
        </div>

        <div className="flex items-center gap-2">
          {/* Period selector */}
          <div className="flex items-center bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            {(['YTD', 'Q1', 'Q2', 'Q3', 'Q4'] as Period[]).map(p => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={clsx(
                  'px-4 py-2 text-xs font-bold tracking-wide transition-all',
                  period === p ? 'bg-gray-900 text-white' : 'text-gray-500 hover:text-gray-800 hover:bg-gray-50',
                )}
              >
                {p}
              </button>
            ))}
          </div>

          {/* VS PLAN */}
          <button
            onClick={() => setVsPlan(v => !v)}
            className={clsx(
              'px-4 py-2 text-xs font-bold tracking-wide border rounded-xl transition-all shadow-sm',
              vsPlan ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-500 border-gray-200 hover:text-gray-800 hover:border-gray-300',
            )}
          >
            VS PLAN
          </button>

          <button className="flex items-center gap-1.5 px-4 py-2 bg-gray-900 text-white text-xs font-bold tracking-wide rounded-xl hover:bg-gray-700 transition-colors shadow-sm">
            <Download size={13} />
            EXPORT
          </button>
        </div>
      </div>

      {/* ── KPI cards (display only) ──────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-4">
        {TILE_META.map((meta, i) => (
          <KpiCard
            key={meta.id}
            meta={meta}
            val={tileVals[i]}
            period={period}
            vsPlan={vsPlan}
          />
        ))}
      </div>

      {/* ── Lower section ────────────────────────────────────────────────── */}
      <div className="space-y-3">

        {/* Section label + segmented toggle — controls BOTH widgets */}
        <div className="flex items-end justify-between px-1">
          <div>
            <p className="text-[10px] font-bold tracking-[0.2em] text-gray-400 uppercase">AI Investment Breakdown</p>
            <h2 className="text-lg font-black text-gray-900 mt-0.5 tracking-tight">{costLabel}</h2>
          </div>
          <div className="flex items-center bg-white border border-gray-200 rounded-xl p-1 gap-0.5 shadow-sm">
            {DRILL_VIEWS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setDrillView(key)}
                className={clsx(
                  'px-4 py-2 text-xs font-bold rounded-lg transition-all duration-200 tracking-wide',
                  drillView === key ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-500 hover:text-gray-700',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Two widgets — both react to period + toggle + VS PLAN */}
        <div className="grid grid-cols-5 gap-4">
          <BarChartWidget drill={drill} view={drillView} vsPlan={vsPlan} costLabel={costLabel} />
          <UseCaseWidget  drill={drill} vsPlan={vsPlan} />
        </div>

      </div>
    </div>
  )
}
