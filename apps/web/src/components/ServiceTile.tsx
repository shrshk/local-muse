import type { ComponentStatus } from '../types';

interface Props {
  name: string;
  status: ComponentStatus | 'connecting';
  detail?: string | null;
  latencyMs?: number | null;
}

export function ServiceTile({ name, status, detail, latencyMs }: Props) {
  return (
    <li className={`tile tile--${status}`}>
      <div className="tile__head">
        <span className="tile__dot" aria-hidden />
        <span className="tile__name">{name}</span>
        <span className="tile__status">{status}</span>
      </div>
      {(detail || latencyMs != null) && (
        <div className="tile__meta">
          {detail && <span>{detail}</span>}
          {latencyMs != null && <span>{latencyMs} ms</span>}
        </div>
      )}
    </li>
  );
}
