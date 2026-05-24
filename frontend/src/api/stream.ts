import client from './client'

export async function fetchStreamConfig(): Promise<{ poll_interval_seconds: number }> {
  const { data } = await client.get<{ poll_interval_seconds: number }>('/stream/config')
  return data
}
