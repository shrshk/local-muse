import { type FormEvent, useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { AppNotification, Conversation, Goal } from '../types';

const POLL_MS = 10_000;

function schedule(goal: Goal): string {
  if (goal.kind === 'recurring') return `every ${goal.every_minutes} min`;
  return goal.fire_at ? `once at ${new Date(goal.fire_at).toLocaleString()}` : 'once';
}

function GoalForm({ conversations, onCreated }: { conversations: Conversation[]; onCreated: () => void }) {
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [condition, setCondition] = useState('');
  const [mode, setMode] = useState<'after_minutes' | 'every_minutes'>('after_minutes');
  const [minutes, setMinutes] = useState(60);
  const [conversationId, setConversationId] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!conversationId && conversations.length) setConversationId(conversations[0].id);
  }, [conversations, conversationId]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.createGoal({
        conversation_id: conversationId,
        title,
        objective,
        condition: condition || null,
        [mode]: minutes,
      });
      setTitle('');
      setObjective('');
      setCondition('');
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!conversations.length) return <p className="muted">Start a chat first; goals report into a conversation.</p>;
  return (
    <form className="card form" onSubmit={submit}>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Laptop price" />
      </label>
      <label>
        What to check
        <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="The price of … on …" />
      </label>
      <label>
        Notify when (optional; otherwise when the result changes)
        <input value={condition} onChange={(e) => setCondition(e.target.value)} placeholder="price is below $900" />
      </label>
      <div className="goal-form__timing">
        <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
          <option value="after_minutes">Once, after</option>
          <option value="every_minutes">Every</option>
        </select>
        <input type="number" min={1} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
        <span className="muted">minutes</span>
      </div>
      <label>
        Report into
        <select value={conversationId} onChange={(e) => setConversationId(e.target.value)}>
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title ?? 'Untitled'}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="form__error">{error}</p>}
      <button type="submit" disabled={!title.trim() || !objective.trim()}>
        Create goal
      </button>
    </form>
  );
}

export function GoalsPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);

  const load = useCallback(async () => {
    const [g, n, c] = await Promise.all([api.goals(), api.notifications(), api.conversations()]);
    setGoals(g);
    setNotifications(n);
    setConversations(c);
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const open = goals.filter((g) => g.status === 'active' || g.status === 'pending');
  const past = goals.filter((g) => g.status !== 'active' && g.status !== 'pending').slice(0, 10);
  const unread = notifications.filter((n) => !n.read_at);

  return (
    <main className="page">
      <header className="page__head">
        <h2>Goals</h2>
        <p className="page__sub">Checks that run later or on a schedule, and tell you when something matters.</p>
      </header>

      <h3 className="section-title">Notifications {unread.length > 0 && <span className="badge">{unread.length} new</span>}</h3>
      <ul className="facts">
        {notifications.length === 0 && <p className="muted">Nothing yet.</p>}
        {notifications.slice(0, 20).map((n) => (
          <li key={n.id} className={`fact ${n.read_at ? 'fact--read' : ''}`}>
            <div className="fact__head">
              <strong>{n.title}</strong>
              <span className="muted">{new Date(n.created_at).toLocaleString()}</span>
            </div>
            <span>{n.body}</span>
            {!n.read_at && (
              <button className="link" onClick={() => void api.markRead(n.id).then(load)}>
                Mark read
              </button>
            )}
          </li>
        ))}
      </ul>

      <h3 className="section-title">Active</h3>
      <ul className="facts">
        {open.length === 0 && <p className="muted">No active goals. Ask in chat, e.g. “check this again tomorrow”.</p>}
        {open.map((g) => (
          <li key={g.id} className="fact">
            <div className="fact__head">
              <strong>{g.title}</strong>
              <span className="muted">{schedule(g)}</span>
            </div>
            <span className="muted">{g.objective}</span>
            {g.condition && <span className="muted">Notify when: {g.condition}</span>}
            <span className="muted">
              {g.next_run_at ? `next ${new Date(g.next_run_at).toLocaleString()} · ` : ''}
              {g.run_count} runs · {g.notify_count} notifications
              {g.last_value ? ` · last: ${g.last_value}` : ''}
            </span>
            <button className="link" onClick={() => void api.cancelGoal(g.id).then(load)}>
              Cancel
            </button>
          </li>
        ))}
      </ul>

      <h3 className="section-title">New goal</h3>
      <GoalForm conversations={conversations} onCreated={() => void load()} />

      {past.length > 0 && (
        <>
          <h3 className="section-title">Finished</h3>
          <ul className="facts">
            {past.map((g) => (
              <li key={g.id} className="fact fact--read">
                <div className="fact__head">
                  <strong>{g.title}</strong>
                  <span className="muted">{g.status}</span>
                </div>
                {g.last_summary && <span className="muted">{g.last_summary}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
