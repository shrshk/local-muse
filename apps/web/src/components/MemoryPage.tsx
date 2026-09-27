import { type FormEvent, useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { ProfileFact } from '../types';

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
    </main>
  );
}
