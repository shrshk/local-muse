import { type FormEvent, type MouseEvent, useEffect, useState } from 'react';

import { api } from '../api';
import { centrifuge } from '../realtime';
import type { BrowserSession } from '../types';

const VIEWPORT_WIDTH = 1280;

interface BrowserEvent {
  type: string;
  data: { frame_version?: number; url?: string; mode?: 'agent' | 'human' };
}

/** Live view of the agent's browser. Frames arrive as version numbers; the image is fetched. */
export function BrowserViewer({ session, onChange }: { session: BrowserSession; onChange: () => void }) {
  const [version, setVersion] = useState(session.frame_version);
  const [url, setUrl] = useState(session.current_url ?? '');
  const [mode, setMode] = useState(session.mode);
  const [open, setOpen] = useState(true);
  const [text, setText] = useState('');
  const [target, setTarget] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setVersion(session.frame_version);
    setMode(session.mode);
    setUrl(session.current_url ?? '');
  }, [session.frame_version, session.mode, session.current_url]);

  useEffect(() => {
    const channel = `browser:${session.id}`;
    const client = centrifuge();
    const sub =
      client.getSubscription(channel) ??
      client.newSubscription(channel, {
        getToken: async () => (await api.subscribeBrowserToken(session.id)).token,
      });
    sub.on('publication', (ctx) => {
      const event = ctx.data as BrowserEvent;
      if (event.type === 'browser.frame' && event.data.frame_version) {
        setVersion((v) => Math.max(v, event.data.frame_version ?? v));
        if (event.data.url) setUrl(event.data.url);
      }
      if (event.type === 'browser.mode' && event.data.mode) setMode(event.data.mode);
    });
    sub.subscribe();
    return () => {
      sub.removeAllListeners();
      sub.unsubscribe();
      client.removeSubscription(sub);
    };
  }, [session.id]);

  const act = async (input: Record<string, string | number>) => {
    setError(null);
    try {
      const result = await api.browserInput(session.id, input);
      setUrl(result.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggle = async () => {
    const next = mode === 'human' ? 'agent' : 'human';
    setError(null);
    try {
      await api.setBrowserMode(session.id, next);
      setMode(next);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const clickFrame = (e: MouseEvent<HTMLImageElement>) => {
    if (mode !== 'human') return;
    const box = e.currentTarget.getBoundingClientRect();
    const scale = VIEWPORT_WIDTH / box.width;
    void act({
      kind: 'click',
      x: Math.round((e.clientX - box.left) * scale),
      y: Math.round((e.clientY - box.top) * scale),
    });
  };

  const typeText = (e: FormEvent) => {
    e.preventDefault();
    if (text) void act({ kind: 'type', text }).then(() => setText(''));
  };

  const go = (e: FormEvent) => {
    e.preventDefault();
    if (target) void act({ kind: 'navigate', url: target });
  };

  return (
    <section className={`browser browser--${mode}`}>
      <div className="browser__bar">
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? '▾' : '▸'} Browser
        </button>
        {session.context === 'authenticated' && <span className="browser__badge">logged-in profile</span>}
        <span className="browser__url" title={url}>
          {url || 'about:blank'}
        </span>
        <button className={mode === 'human' ? 'browser__handback' : ''} onClick={toggle}>
          {mode === 'human' ? 'Hand back' : 'Take control'}
        </button>
      </div>
      {open && (
        <>
          {version > 0 ? (
            <img
              className="browser__frame"
              src={`/api/browser/${session.id}/frame?v=${version}`}
              alt="Agent browser"
              onClick={clickFrame}
            />
          ) : (
            <p className="muted">No page yet.</p>
          )}
          {mode === 'human' && (
            <div className="browser__controls">
              <form onSubmit={go}>
                <input placeholder="https://…" value={target} onChange={(e) => setTarget(e.target.value)} />
                <button type="submit">Go</button>
              </form>
              <form onSubmit={typeText}>
                <input
                  type={session.context === 'authenticated' ? 'password' : 'text'}
                  autoComplete="off"
                  placeholder={session.context === 'authenticated' ? 'Type (hidden, e.g. a password)' : 'Type into the page'}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <button type="submit">Type</button>
                <button type="button" onClick={() => void act({ kind: 'press', key: 'Enter' })}>
                  Enter
                </button>
              </form>
              <div className="browser__scroll">
                <button onClick={() => void act({ kind: 'scroll', direction: 'up' })}>Scroll up</button>
                <button onClick={() => void act({ kind: 'scroll', direction: 'down' })}>Scroll down</button>
              </div>
              <p className="muted">You have control. The agent waits until you hand it back.</p>
            </div>
          )}
          {error && <p className="form__error">{error}</p>}
        </>
      )}
    </section>
  );
}
