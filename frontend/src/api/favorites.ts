import client from './client'
import type { Favorite } from '../types'

export async function listFavorites(): Promise<Favorite[]> {
  const { data } = await client.get<Favorite[]>('/favorites')
  return data
}

export async function createFavorite(payload: Omit<Favorite, 'id' | 'is_default' | 'user_id'>): Promise<Favorite> {
  const { data } = await client.post<Favorite>('/favorites', payload)
  return data
}

export async function deleteFavorite(id: number): Promise<void> {
  await client.delete(`/favorites/${id}`)
}

export async function runFavorite(id: number): Promise<{ name: string; chart_type: string; sql: string; data: Record<string, unknown>[] }> {
  const { data } = await client.post(`/favorites/${id}/run`)
  return data
}
