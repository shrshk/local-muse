import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api';
import type { Action, Conversation, Message } from '../types';
import { ToolCallChip } from './ToolCallChip';

type TimelineItem = { kind: 'message'; at: string; message: Message } | { kind: 'action'; at: string; action: Action };

function timeline(messages: Message[], actions: Action[]): TimelineItem[] {
  const items: TimelineItem[] = [
    ...messages.map((m) => ({ kind: 'message' as const, at: m.created_at, message: m })),
    ...actions.map((a) => ({ kind: 'action' as const, at: a.created_at, action: a })),
  ];
  return items.sort((a, b) => a.at.localeCompare(b.at));
}

export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(async () => {
    const list = await api.conversations();
    setConversations(list);
    return list;
  }, []);

  const loadTimeline = useCallback(async (id: string) => {
    const [messages, actions] = await Promise.all([api.messages(id), api.actions(id)]);
    setItems(timeline(messages, actions));
  }, []);

  useEffect(() => {
    void loadConversations().then((list) => {
      if (list.length > 0) setActiveId((current) => current ?? list[0].id);
    });
  }, [loadConversations]);

  // Set when send() creates the conversation, so the effect below does not race the turn.
  const skipNextLoad = useRef(false);

  useEffect(() => {
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      return;
    }
    if (activeId) void loadTimeline(activeId);
    else setItems([]);
  }, [activeId, loadTimeline]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items, pending]);

  const newConversation = async () => {
    const conversation = await api.createConversation();
    setConversations((list) => [conversation, ...list]);
    setActiveId(conversation.id);
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content || pending) return;
    let id = activeId;
    if (!id) {
      const conversation = await api.createConversation();
      id = conversation.id;
      skipNextLoad.current = true;
      setActiveId(id);
    }
    setDraft('');
    setPending(content);
    setError(null);
    try {
      await api.send(id, content);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(null);
      await Promise.all([loadTimeline(id), loadConversations()]);
    }
  };

  return (
    <div className="chat">
      <aside className="chat__sidebar">
        <button className="chat__new" onClick={newConversation}>
          New chat
        </button>
        <ul>
          {conversations.map((c) => (
            <li key={c.id}>
              <button className={c.id === activeId ? 'active' : ''} onClick={() => setActiveId(c.id)}>
                {c.title ?? 'Untitled'}
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="chat__main">
        <div className="chat__log">
          {items.length === 0 && !pending && <p className="muted">Ask anything. Try: “What time is it in Tokyo?”</p>}
          {items.map((item) =>
            item.kind === 'message' ? (
              <div key={item.message.id} className={`bubble bubble--${item.message.role}`}>
                {item.message.content}
              </div>
            ) : (
              <ToolCallChip
                key={item.action.action_id}
                tool={item.action.tool}
                args={item.action.args}
                decision={item.action.decision}
                ok={item.action.result?.ok ?? null}
                output={item.action.result?.output}
                error={item.action.result?.error}
              />
            ),
          )}
          {pending && (
            <>
              <div className="bubble bubble--user">{pending}</div>
              <div className="bubble bubble--assistant bubble--thinking">Thinking…</div>
            </>
          )}
          {error && <p className="form__error">{error}</p>}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={send}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Message Local Muse"
            rows={2}
          />
          <button type="submit" disabled={!draft.trim() || pending !== null}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
