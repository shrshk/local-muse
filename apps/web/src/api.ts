import type { ConnectionToken, HealthReport } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} → ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthReport>('/api/health'),
  realtimeToken: () => request<ConnectionToken>('/api/realtime/token', { method: 'POST' }),
};
