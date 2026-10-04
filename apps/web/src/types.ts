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
  role: 'user' | 'assistant' | 'event';
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

export interface ConversationStatus {
  running_turn_id: string | null;
  pending_turn_ids: string[];
  active_topic_ids: string[];
  waiting_approval_ids: string[];
  last_error: string | null;
}

export type TopicStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Topic {
  id: string;
  conversation_id: string;
  title: string;
  objective: string;
  status: TopicStatus;
  result: Json;
  created_at: string;
  finished_at: string | null;
}

export interface TopicMemoryDocument {
  summary: string;
  objective: string;
  decisions: string[];
  sources: string[];
  successful_commands: string[];
  failed_approaches: string[];
  important_artifacts: string[];
  unfinished_work: string[];
  next_actions: string[];
}

export interface TopicMemory {
  topic_id: string;
  document: TopicMemoryDocument;
  version: number;
  updated_at: string;
}

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'DENIED' | 'EXPIRED';

export interface Approval {
  id: string;
  action_id: string;
  approval_key: string;
  conversation_id: string;
  topic_id: string | null;
  tool: string;
  args: Record<string, Json>;
  destination: string | null;
  summary: string;
  status: ApprovalStatus;
  decided_by: string | null;
  channel: string | null;
  decided_at: string | null;
  expires_at: string;
  created_at: string;
}

export interface BrowserSession {
  id: string;
  conversation_id: string;
  topic_id: string | null;
  context: string;
  mode: 'agent' | 'human';
  current_url: string | null;
  status: string;
  frame_version: number;
  updated_at: string;
}

export interface AllowlistEntry {
  domain: string;
  context: string;
  created_at: string;
}

export interface ConversationState {
  conversation: Conversation;
  seq: number;
  messages: Message[];
  actions: Action[];
  topics: Topic[];
  approvals: Approval[];
  browser_sessions: BrowserSession[];
  status: ConversationStatus;
}

export interface SendAck {
  message_id: string;
  seq: number;
  turn_id: string;
}

export interface RealtimeEvent {
  type: string;
  seq: number;
  ts: string;
  data: { turn_id?: string; text?: string; attempt?: number; reason?: string; [key: string]: Json | undefined };
}

export interface ProfileFact {
  key: string;
  value: string;
  source: 'user' | 'agent';
  updated_at: string;
}

export interface Goal {
  id: string;
  conversation_id: string;
  title: string;
  objective: string;
  condition: string | null;
  kind: 'once' | 'recurring';
  fire_at: string | null;
  every_minutes: number | null;
  status: 'pending' | 'active' | 'completed' | 'cancelled';
  last_value: string | null;
  last_condition: boolean | null;
  last_summary: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  run_count: number;
  notify_count: number;
  created_at: string;
  running_since: string | null;
  progress: string | null;
  progress_steps: number;
}

export interface AppNotification {
  id: string;
  conversation_id: string | null;
  goal_id: string | null;
  kind: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
}
