import { Centrifuge } from 'centrifuge';
import { useEffect, useState } from 'react';

import { api } from '../api';

export type RealtimeState = 'connecting' | 'connected' | 'disconnected';

function websocketUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/connection/websocket`;
}

// Connects with a backend-minted JWT. Proves the token path end to end; no channels yet.
export function useRealtime(): RealtimeState {
  const [state, setState] = useState<RealtimeState>('connecting');

  useEffect(() => {
    const client = new Centrifuge(websocketUrl(), {
      getToken: async () => (await api.realtimeToken()).token,
    });
    client.on('connecting', () => setState('connecting'));
    client.on('connected', () => setState('connected'));
    client.on('disconnected', () => setState('disconnected'));
    client.connect();
    return () => client.disconnect();
  }, []);

  return state;
}
