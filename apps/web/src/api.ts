import type {
  ConnectionToken,
  Conversation,
  ConversationState,
  HealthReport,
  Principal,
  SendAck,
  Topic,
  TopicMemory,
  TopicMemoryDocument,
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
  state: (id: string) => request<ConversationState>(`/api/conversations/${id}/state`),
  send: (id: string, content: string) => post<SendAck>(`/api/conversations/${id}/messages`, { content }),
  cancelTopic: (id: string) => post<Topic>(`/api/topics/${id}/cancel`),
  topicMemory: (id: string) => request<TopicMemory>(`/api/topics/${id}/memory`),
  updateTopicMemory: (id: string, document: TopicMemoryDocument, version: number) =>
    request<TopicMemory>(`/api/topics/${id}/memory`, {
      method: 'PUT',
      body: JSON.stringify({ document, version }),
    }),
  subscribeToken: (conversationId: string) =>
    post<ConnectionToken>('/api/realtime/subscribe_token', { conversation_id: conversationId }),
};
