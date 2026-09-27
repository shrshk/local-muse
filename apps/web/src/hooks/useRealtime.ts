import { useEffect, useState } from 'react';

import { centrifuge } from '../realtime';

export type RealtimeState = 'connecting' | 'connected' | 'disconnected';

export function useRealtime(): RealtimeState {
  const [state, setState] = useState<RealtimeState>(() =>
    centrifuge().state === 'connected' ? 'connected' : 'connecting',
  );

  useEffect(() => {
    const client = centrifuge();
    const onConnecting = () => setState('connecting');
    const onConnected = () => setState('connected');
    const onDisconnected = () => setState('disconnected');
    client.on('connecting', onConnecting);
    client.on('connected', onConnected);
    client.on('disconnected', onDisconnected);
    return () => {
      client.removeListener('connecting', onConnecting);
      client.removeListener('connected', onConnected);
      client.removeListener('disconnected', onDisconnected);
    };
  }, []);

  return state;
}
