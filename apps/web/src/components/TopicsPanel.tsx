import { useEffect, useState } from 'react';

import { api } from '../api';
import type { Topic, TopicMemory, TopicMemoryDocument } from '../types';

const ACTIVE = new Set(['pending', 'running']);

function MemoryEditor({ topic, onClose }: { topic: Topic; onClose: () => void }) {
  const [memory, setMemory] = useState<TopicMemory | null>(null);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.topicMemory(topic.id).then((m) => {
      if (cancelled) return;
      setMemory(m);
      setDraft(JSON.stringify(m.document, null, 2));
    });
    return () => {
      cancelled = true;
    };
  }, [topic.id]);

  const save = async () => {
    if (!memory) return;
    setError(null);
    let document: TopicMemoryDocument;
    try {
      document = JSON.parse(draft) as TopicMemoryDocument;
    } catch {
      setError('Not valid JSON');
      return;
    }
    try {
      const saved = await api.updateTopicMemory(topic.id, document, memory.version);
      setMemory(saved);
      setDraft(JSON.stringify(saved.document, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!memory) return <p className="muted">Loading memory…</p>;
  return (
    <div className="topic__memory">
      <p className="topic__summary">{memory.document.summary || 'No summary yet.'}</p>
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={10} spellCheck={false} />
      {error && <p className="form__error">{error}</p>}
      <div className="topic__actions">
        <span className="muted">version {memory.version}</span>
        <button onClick={save}>Save memory</button>
        <button className="link" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

export function TopicsPanel({ topics, onChange }: { topics: Topic[]; onChange: () => void }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (topics.length === 0) return null;

  const cancel = async (id: string) => {
    await api.cancelTopic(id);
    onChange();
  };

  return (
    <section className="topics">
      {topics.map((topic) => (
        <div key={topic.id} className={`topic topic--${topic.status}`}>
          <div className="topic__head">
            <span className="topic__dot" aria-hidden />
            <strong className="topic__title">{topic.title}</strong>
            <span className="topic__status">{topic.status}</span>
            {ACTIVE.has(topic.status) && (
              <button className="link" onClick={() => cancel(topic.id)}>
                Cancel
              </button>
            )}
            <button className="link" onClick={() => setOpenId(openId === topic.id ? null : topic.id)}>
              Memory
            </button>
          </div>
          {openId === topic.id && <MemoryEditor topic={topic} onClose={() => setOpenId(null)} />}
        </div>
      ))}
    </section>
  );
}
