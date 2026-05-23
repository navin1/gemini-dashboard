import client from './client'
import type { GlossaryTerm } from '../types'

export async function listTerms(): Promise<GlossaryTerm[]> {
  const { data } = await client.get<GlossaryTerm[]>('/glossary')
  return data
}

export async function createTerm(payload: { term: string; definition: string; example?: string }): Promise<GlossaryTerm> {
  const { data } = await client.post<GlossaryTerm>('/glossary', payload)
  return data
}

export async function updateTerm(id: number, payload: Partial<{ term: string; definition: string; example: string }>): Promise<GlossaryTerm> {
  const { data } = await client.put<GlossaryTerm>(`/glossary/${id}`, payload)
  return data
}

export async function deleteTerm(id: number): Promise<void> {
  await client.delete(`/glossary/${id}`)
}
