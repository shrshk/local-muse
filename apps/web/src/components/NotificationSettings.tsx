import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { NotificationPreference, NotifyLevel, PushDevice } from '../types';

const LEVEL_LABELS: Record<NotifyLevel, string> = {
  all: 'All',
  important: 'Important only',
  none: 'Feed only',
};

function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

function Unsupported() {
  if (!window.isSecureContext) {
    return (
      <p className="muted">
        Notifications need HTTPS. Open Muse through your Tailscale address (https://…ts.net), see
        docs/phone-setup.md.
      </p>
    );
  }
  return (
    <p className="muted">
      This browser cannot receive push here. On iPhone: Share → Add to Home Screen, open Muse from the home
      screen, then enable notifications.
    </p>
  );
}

/** This device's push subscription, and the interruption budget per kind. */
export function NotificationSettings() {
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [devices, setDevices] = useState<PushDevice[]>([]);
  const [prefs, setPrefs] = useState<NotificationPreference[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [d, p] = await Promise.all([api.pushDevices(), api.notificationPreferences()]);
    setDevices(d);
    setPrefs(p);
    if (pushSupported()) setSubscribed((await currentSubscription()) !== null);
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => setMessage(String(err)));
  }, [load]);

  const enable = async () => {
    setMessage(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setMessage('Notifications are blocked for this site; allow them in the browser settings.');
        return;
      }
      const { public_key } = await api.pushKey();
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes(public_key),
      });
      await api.pushSubscribe(subscription.toJSON());
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  };

  const disable = async () => {
    const subscription = await currentSubscription();
    if (subscription) {
      await api.pushUnsubscribe(subscription.endpoint);
      await subscription.unsubscribe();
    }
    await load();
  };

  const test = async () => {
    await api.pushTest();
    setMessage('Sent. It should arrive in a few seconds.');
  };

  const save = async (pref: NotificationPreference) => {
    const saved = await api.setNotificationPreference(pref.kind, pref.level, pref.daily_cap);
    setPrefs((all) => all.map((p) => (p.kind === saved.kind ? saved : p)));
  };

  return (
    <section className="card form">
      <h3 className="section-title">Notifications on this device</h3>
      {!pushSupported() ? (
        <Unsupported />
      ) : subscribed ? (
        <div className="row">
          <span>On</span>
          <button onClick={() => void test()}>Send test</button>
          <button className="link" onClick={() => void disable()}>
            Turn off
          </button>
        </div>
      ) : (
        <button onClick={() => void enable()} disabled={subscribed === null}>
          Enable notifications
        </button>
      )}
      <p className="muted">
        {devices.length} device{devices.length === 1 ? '' : 's'} registered. Pushes carry no content; the text
        is fetched from this Mac.
      </p>
      {message && <p className="muted">{message}</p>}

      <h3 className="section-title">What may interrupt you</h3>
      <p className="muted">Approvals always notify. Everything else also waits in the Goals feed.</p>
      {prefs.map((p) => (
        <div key={p.kind} className="row">
          <strong className="row__label">{p.kind}</strong>
          <select value={p.level} onChange={(e) => void save({ ...p, level: e.target.value as NotifyLevel })}>
            {(Object.keys(LEVEL_LABELS) as NotifyLevel[]).map((level) => (
              <option key={level} value={level}>
                {LEVEL_LABELS[level]}
              </option>
            ))}
          </select>
          <label className="row__cap">
            max/day
            <input
              type="number"
              min={0}
              max={50}
              value={p.daily_cap}
              onChange={(e) => void save({ ...p, daily_cap: Number(e.target.value) })}
            />
          </label>
        </div>
      ))}
    </section>
  );
}
