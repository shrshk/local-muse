import { Centrifuge } from 'centrifuge';

import { api } from './api';

let client: Centrifuge | null = null;

function websocketUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/connection/websocket`;
}

/** One websocket per tab, authenticated with a backend-minted connection token. */
export function centrifuge(): Centrifuge {
  if (!client) {
    client = new Centrifuge(websocketUrl(), {
      getToken: async () => (await api.realtimeToken()).token,
    });
    client.connect();
  }
  return client;
}

export function disconnectRealtime(): void {
  client?.disconnect();
  client = null;
}
