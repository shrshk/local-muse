import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api';
import { useConversation } from '../hooks/useConversation';
import type { Action, Conversation, Message } from '../types';
import { ApprovalCard } from './ApprovalCard';
import { BrowserViewer } from './BrowserViewer';
import { ToolCallChip } from './ToolCallChip';
import { TopicsPanel } from './TopicsPanel';

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
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const { state, streaming, error, reload, setError } = useConversation(activeId);
  const endRef = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(async () => {
    const list = await api.conversations();
    setConversations(list);
    return list;
  }, []);

  useEffect(() => {
    void loadConversations().then((list) => {
      if (list.length > 0) setActiveId((current) => current ?? list[0].id);
    });
  }, [loadConversations]);

  const items = state ? timeline(state.messages, state.actions) : [];
  const busy =
    sending ||
    streaming !== null ||
    Boolean(state?.status.running_turn_id) ||
    (state?.status.pending_turn_ids.length ?? 0) > 0;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items.length, streaming?.text]);

  const newConversation = async () => {
    const conversation = await api.createConversation();
    setConversations((list) => [conversation, ...list]);
    setActiveId(conversation.id);
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    try {
      let id = activeId;
      if (!id) {
        const conversation = await api.createConversation();
        id = conversation.id;
        setActiveId(id);
      }
      await api.send(id, content);
      setDraft('');
      if (id === activeId) await reload();
      await loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
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
        {state && <TopicsPanel topics={state.topics} onChange={() => void reload()} />}
        {state?.browser_sessions
          .filter((b) => b.status === 'open')
          .map((b) => <BrowserViewer key={b.id} session={b} onChange={() => void reload()} />)}
        <div className="chat__log">
          {items.length === 0 && !busy && <p className="muted">Ask anything. Try: “What time is it in Tokyo?”</p>}
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
          {state?.approvals
            .filter((a) => a.status === 'PENDING')
            .map((a) => (
              <ApprovalCard key={a.id} approval={a} onDecided={() => void reload()} />
            ))}
          {busy && !state?.status.waiting_approval_ids.length && (
            <div className={`bubble bubble--assistant ${streaming?.text ? '' : 'bubble--thinking'}`}>
              {streaming?.text || 'Thinking…'}
            </div>
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
          <button type="submit" disabled={!draft.trim() || sending}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
