import { useEffect, useState } from 'react';

import { api } from './api';
import { disconnectRealtime } from './realtime';
import { ApprovalsPage } from './components/ApprovalsPage';
import { ChatPage } from './components/ChatPage';
import { GoalsPage } from './components/GoalsPage';
import { LoginForm } from './components/LoginForm';
import { MemoryPage } from './components/MemoryPage';
import { StatusPage } from './components/StatusPage';
import type { Principal } from './types';

const TABS = ['chat', 'approvals', 'goals', 'memory', 'status'] as const;
type Tab = (typeof TABS)[number];

/** `/?tab=approvals` opens that tab: notifications deep-link here. */
function initialTab(): Tab {
  const wanted = new URLSearchParams(window.location.search).get('tab');
  return TABS.find((t) => t === wanted) ?? 'chat';
}

export function App() {
  const [user, setUser] = useState<Principal | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>(initialTab);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) return null;
  if (user === null) return <LoginForm onLogin={setUser} />;

  const logout = async () => {
    await api.logout();
    disconnectRealtime();
    setUser(null);
  };

  return (
    <div className="shell">
      <header className="shell__head">
        <strong>Local Muse</strong>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
        <button className="link" onClick={logout}>
          Sign out
        </button>
      </header>
      {tab === 'chat' && <ChatPage />}
      {tab === 'approvals' && <ApprovalsPage />}
      {tab === 'goals' && <GoalsPage />}
      {tab === 'memory' && <MemoryPage />}
      {tab === 'status' && <StatusPage />}
    </div>
  );
}
