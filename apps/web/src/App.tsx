import { useEffect, useState } from 'react';

import { api } from './api';
import { disconnectRealtime } from './realtime';
import { ApprovalsPage } from './components/ApprovalsPage';
import { ChatPage } from './components/ChatPage';
import { LoginForm } from './components/LoginForm';
import { MemoryPage } from './components/MemoryPage';
import { StatusPage } from './components/StatusPage';
import type { Principal } from './types';

type Tab = 'chat' | 'approvals' | 'memory' | 'status';

export function App() {
  const [user, setUser] = useState<Principal | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>('chat');

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
          {(['chat', 'approvals', 'memory', 'status'] as const).map((t) => (
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
      {tab === 'memory' && <MemoryPage />}
      {tab === 'status' && <StatusPage />}
    </div>
  );
}
