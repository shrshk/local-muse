/// <reference lib="webworker" />
// Service worker: caches the app shell (never API data) and shows pushes.
// A push carries only a notification id. The text is fetched from the Mac over Tailscale, so
// the push service (Apple, Google, ...) never sees what the notification is about.
import { clientsClaim } from 'workbox-core';
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('index.html'), {
    denylist: [/^\/api\//, /^\/connection\//],
  }),
);
self.skipWaiting();
clientsClaim();

interface StoredNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
}

function tabFor(kind: string): string {
  if (kind === 'approval') return 'approvals';
  if (kind === 'goal' || kind === 'test') return 'goals';
  return 'chat';
}

async function show(id: string | undefined): Promise<void> {
  let title = 'Local Muse';
  let body = 'Muse needs you';
  let url = '/';
  if (id) {
    try {
      const response = await fetch(`/api/notifications/${encodeURIComponent(id)}`, {
        credentials: 'same-origin',
      });
      if (response.ok) {
        const n = (await response.json()) as StoredNotification;
        title = n.title;
        body = n.body;
        url = `/?tab=${tabFor(n.kind)}`;
      }
    } catch {
      // Offline or signed out: the generic text still tells the user to open the app.
    }
  }
  // Always show something: iOS revokes push for apps that receive pushes silently.
  await self.registration.showNotification(title, {
    body,
    tag: id,
    icon: '/icon.svg',
    data: { url },
  });
}

self.addEventListener('push', (event) => {
  let id: string | undefined;
  try {
    id = (event.data?.json() as { id?: string } | undefined)?.id;
  } catch {
    id = undefined;
  }
  event.waitUntil(show(id));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | undefined)?.url ?? '/';
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const open = windows[0];
      if (open) {
        await open.navigate(url);
        await open.focus();
        return;
      }
      await self.clients.openWindow(url);
    })(),
  );
});
