import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { Approval } from '../types';
import { ApprovalCard } from './ApprovalCard';

const POLL_MS = 5000;

export function ApprovalsPage() {
  const [pending, setPending] = useState<Approval[]>([]);
  const [recent, setRecent] = useState<Approval[]>([]);

  const load = useCallback(async () => {
    const all = await api.approvals();
    setPending(all.filter((a) => a.status === 'PENDING'));
    setRecent(all.filter((a) => a.status !== 'PENDING').slice(-10).reverse());
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <main className="page">
      <header className="page__head">
        <h2>Approvals</h2>
        <p className="page__sub">Actions with external effects wait here until you decide.</p>
      </header>
      <div className="approvals">
        {pending.length === 0 && <p className="muted">Nothing waiting.</p>}
        {pending.map((a) => (
          <ApprovalCard key={a.id} approval={a} onDecided={() => void load()} />
        ))}
      </div>
      {recent.length > 0 && (
        <>
          <h3 className="section-title">Recent decisions</h3>
          <ul className="facts">
            {recent.map((a) => (
              <li key={a.id} className="fact">
                <div className="fact__head">
                  <code>{a.tool}</code>
                  <span className={`badge badge--${a.status.toLowerCase()}`}>{a.status}</span>
                </div>
                <span className="muted">{a.summary}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
