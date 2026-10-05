import { useHealth } from '../hooks/useHealth';
import { useRealtime } from '../hooks/useRealtime';
import { NotificationSettings } from './NotificationSettings';
import { ServiceTile } from './ServiceTile';

export function StatusPage() {
  const { report, error } = useHealth();
  const realtime = useRealtime();

  return (
    <main className="page">
      <header className="page__head">
        <h2>Status</h2>
        <p className="page__sub">
          {error
            ? `backend unreachable: ${error}`
            : report
              ? `checked ${new Date(report.checked_at).toLocaleTimeString()}`
              : 'checking…'}
        </p>
      </header>
      <ul className="tiles">
        {error && <ServiceTile name="backend" status="offline" detail={error} />}
        {report?.components.map((c) => (
          <ServiceTile
            key={c.name}
            name={c.name}
            status={c.status}
            detail={c.detail}
            latencyMs={c.latency_ms}
          />
        ))}
        <ServiceTile
          name="realtime (this client)"
          status={realtime === 'connected' ? 'online' : realtime === 'connecting' ? 'connecting' : 'offline'}
          detail="Centrifugo websocket with backend JWT"
        />
      </ul>
      <NotificationSettings />
    </main>
  );
}
