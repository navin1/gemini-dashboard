import client from './client'
import type { ScorecardFTE, ScorecardVendor, ScorecardHierarchy } from '../types'

export async function fetchFTEScorecard(): Promise<ScorecardFTE> {
  const { data } = await client.get<ScorecardFTE>('/scorecard/fte')
  return data
}

export async function fetchVendorScorecard(): Promise<ScorecardVendor> {
  const { data } = await client.get<ScorecardVendor>('/scorecard/vendor')
  return data
}

export async function fetchHierarchyScorecard(): Promise<ScorecardHierarchy> {
  const { data } = await client.get<ScorecardHierarchy>('/scorecard/hierarchy')
  return data
}
