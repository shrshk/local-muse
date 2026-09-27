import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api';
import { centrifuge } from '../realtime';
import type { ConversationState, RealtimeEvent } from '../types';

export interface Streaming {
  turnId: string;
  attempt: number;
  text: string;
}

/**
 * Authoritative state from the API plus live events from Centrifugo.
 * Events with seq <= the state's seq are already reflected; a gap means refetch.
 */
export function useConversation(conversationId: string | null) {
  const [state, setState] = useState<ConversationState | null>(null);
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastSeq = useRef(0);

  const reload = useCallback(async () => {
    if (!conversationId) return;
    const next = await api.state(conversationId);
    lastSeq.current = next.seq;
    setState(next);
    if (!next.status.running_turn_id && next.status.pending_turn_ids.length === 0) setStreaming(null);
    setError(next.status.last_error ? `Last turn failed: ${next.status.last_error}` : null);
  }, [conversationId]);

  useEffect(() => {
    setState(null);
    setStreaming(null);
    setError(null);
    lastSeq.current = 0;
    if (!conversationId) return;

    const channel = `conversation:${conversationId}`;
    const client = centrifuge();
    const sub =
      client.getSubscription(channel) ??
      client.newSubscription(channel, {
        getToken: async () => (await api.subscribeToken(conversationId)).token,
      });

    const onEvent = (event: RealtimeEvent) => {
      if (event.seq <= lastSeq.current) return;
      if (event.seq > lastSeq.current + 1) {
        void reload();
        return;
      }
      lastSeq.current = event.seq;
      const turnId = event.data.turn_id ?? '';
      switch (event.type) {
        case 'agent.started':
          setStreaming({ turnId, attempt: 1, text: '' });
          void reload();
          break;
        case 'agent.token':
          setStreaming((current) => {
            const attempt = event.data.attempt ?? 1;
            // A retried model call starts over; drop the partial text of the failed attempt.
            if (!current || current.turnId !== turnId || attempt > current.attempt) {
              return { turnId, attempt, text: event.data.text ?? '' };
            }
            return { ...current, text: current.text + (event.data.text ?? '') };
          });
          break;
        default:
          // Tool results and final messages change durable state: take it from the API.
          void reload();
      }
    };

    sub.on('publication', (ctx) => onEvent(ctx.data as RealtimeEvent));
    // (Re)subscribed after a disconnect: anything could have happened meanwhile.
    sub.on('subscribed', () => void reload());
    sub.subscribe();
    return () => {
      sub.removeAllListeners();
      sub.unsubscribe();
      client.removeSubscription(sub);
    };
  }, [conversationId, reload]);

  return { state, streaming, error, reload, setError };
}
