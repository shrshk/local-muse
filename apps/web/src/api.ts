import type {
  Action,
  ConnectionToken,
  Conversation,
  HealthReport,
  Message,
  Principal,
  TurnResult,
} from './types';

export class UnauthorizedError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  if (response.status === 401) throw new UnauthorizedError('not logged in');
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${init.method ?? 'GET'} ${path} → ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<HealthReport>('/api/health'),
  realtimeToken: () => post<ConnectionToken>('/api/realtime/token'),

  me: () => request<Principal>('/api/auth/me'),
  login: (username: string, password: string) =>
    post<Principal>('/api/auth/login', { username, password }),
  logout: () => post<void>('/api/auth/logout'),

  conversations: () => request<Conversation[]>('/api/conversations'),
  createConversation: () => post<Conversation>('/api/conversations', {}),
  messages: (id: string) => request<Message[]>(`/api/conversations/${id}/messages`),
  actions: (id: string) => request<Action[]>(`/api/conversations/${id}/actions`),
  send: (id: string, content: string) =>
    post<TurnResult>(`/api/conversations/${id}/messages`, { content }),
};
