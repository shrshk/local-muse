import { useState } from 'react';

import { api } from '../api';
import type { Approval } from '../types';

/** Shows exactly what will run. The decision carries this card's approval_key, so an approval
 *  can only ever apply to these contents. */
export function ApprovalCard({ approval, onDecided }: { approval: Approval; onDecided: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: 'approve' | 'deny') => {
    setBusy(true);
    setError(null);
    try {
      await api.decide(approval, decision);
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="approval">
      <div className="approval__head">
        <strong>Approval needed</strong>
        <code>{approval.tool}</code>
        {approval.destination && <span className="muted">→ {approval.destination}</span>}
      </div>
      <pre className="approval__args">{JSON.stringify(approval.args, null, 2)}</pre>
      <div className="approval__foot">
        <span className="muted">expires {new Date(approval.expires_at).toLocaleString()}</span>
        <button className="approval__deny" disabled={busy} onClick={() => decide('deny')}>
          Deny
        </button>
        <button className="approval__approve" disabled={busy} onClick={() => decide('approve')}>
          Approve
        </button>
      </div>
      {error && <p className="form__error">{error}</p>}
    </div>
  );
}
