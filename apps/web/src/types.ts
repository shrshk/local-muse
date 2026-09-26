export type ComponentStatus = 'online' | 'degraded' | 'offline';

export interface ComponentHealth {
  name: string;
  status: ComponentStatus;
  detail: string | null;
  latency_ms: number | null;
}

export interface HealthReport {
  status: ComponentStatus;
  components: ComponentHealth[];
  checked_at: string;
}

export interface ConnectionToken {
  token: string;
  expires_in: number;
}

export interface Principal {
  id: string;
  username: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  seq: number;
  created_at: string;
}

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export interface Action {
  action_id: string;
  tool: string;
  args: Record<string, Json>;
  decision: string;
  status: string;
  result: { ok: boolean; output: Json; error: string | null } | null;
  created_at: string;
}

export interface ToolCall {
  action_id: string;
  tool: string;
  args: Record<string, Json>;
  decision: string;
  ok: boolean;
  output: Json;
  error: string | null;
}

export interface TurnResult {
  user_message: Message;
  assistant_message: Message;
  tool_calls: ToolCall[];
}
