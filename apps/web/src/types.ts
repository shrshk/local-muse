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
