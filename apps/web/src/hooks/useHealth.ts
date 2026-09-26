import { useEffect, useState } from 'react';

import { api } from '../api';
import type { HealthReport } from '../types';

const POLL_MS = 5000;

export function useHealth(): { report: HealthReport | null; error: string | null } {
  const [report, setReport] = useState<HealthReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await api.health();
        if (!cancelled) {
          setReport(next);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return { report, error };
}
