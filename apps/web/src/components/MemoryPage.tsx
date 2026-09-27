import { type FormEvent, useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { AllowlistEntry, ProfileFact } from '../types';

function FactRow({ fact, onChange }: { fact: ProfileFact; onChange: () => void }) {
  const [value, setValue] = useState(fact.value);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      await api.putProfileFact(fact.key, value);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async () => {
    await api.deleteProfileFact(fact.key);
    onChange();
  };

  return (
    <li className="fact">
      <div className="fact__head">
        <code>{fact.key}</code>
        <span className="muted">{fact.source === 'agent' ? 'saved by Muse' : 'you'}</span>
      </div>
      <div className="fact__edit">
        <input value={value} onChange={(e) => setValue(e.target.value)} />
        <button onClick={save} disabled={value === fact.value}>
          Save
        </button>
        <button className="link" onClick={remove}>
          Delete
        </button>
      </div>
      {error && <p className="form__error">{error}</p>}
    </li>
  );
}

function TrustedSites() {
  const [entries, setEntries] = useState<AllowlistEntry[]>([]);
  const [domain, setDomain] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => setEntries(await api.allowlist()), []);
  useEffect(() => {
    void load();
  }, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.addAllowlist(domain.trim().toLowerCase());
      setDomain('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section>
      <h3 className="section-title">Trusted sites</h3>
      <p className="page__sub">
        In research browsing, clicks and typing on these domains (and their subdomains) run without
        asking. Buttons that look consequential (buy, send, delete…) still ask.
      </p>
      <form className="card form fact-form" onSubmit={add}>
        <input placeholder="docs.python.org" value={domain} onChange={(e) => setDomain(e.target.value)} />
        <button type="submit" disabled={!domain.trim()}>
          Trust
        </button>
        {error && <p className="form__error">{error}</p>}
      </form>
      <ul className="facts">
        {entries.length === 0 && <p className="muted">None. Every research click asks first.</p>}
        {entries.map((entry) => (
          <li key={entry.domain} className="fact fact__row">
            <code>{entry.domain}</code>
            <button
              className="link"
              onClick={() => void api.removeAllowlist(entry.domain).then(load)}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function MemoryPage() {
  const [facts, setFacts] = useState<ProfileFact[]>([]);
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => setFacts(await api.profileFacts()), []);
  useEffect(() => {
    void load();
  }, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.putProfileFact(key.trim(), value.trim());
      setKey('');
      setValue('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <main className="page">
      <header className="page__head">
        <h2>Profile memory</h2>
        <p className="page__sub">Long-lived facts Muse uses in every conversation. Never secrets.</p>
      </header>
      <form className="card form fact-form" onSubmit={add}>
        <input placeholder="key, e.g. home_city" value={key} onChange={(e) => setKey(e.target.value)} />
        <input placeholder="value" value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="submit" disabled={!key.trim() || !value.trim()}>
          Add
        </button>
        {error && <p className="form__error">{error}</p>}
      </form>
      <ul className="facts">
        {facts.length === 0 && <p className="muted">No facts yet.</p>}
        {facts.map((f) => (
          <FactRow key={`${f.key}:${f.updated_at}`} fact={f} onChange={() => void load()} />
        ))}
      </ul>
      <TrustedSites />
    </main>
  );
}
