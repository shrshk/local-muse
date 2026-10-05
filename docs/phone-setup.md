# Phone setup (Tailscale + home-screen app)

Local Muse never opens a port to the internet. Your phone reaches the Mac over Tailscale, a
private network between your own devices. `tailscale serve` gives the Mac an HTTPS address with
a real certificate, which iOS needs for an installed web app and for notifications.

## One-time setup

1. Install Tailscale on the Mac (`brew install --cask tailscale`, or the App Store) and on the
   iPhone. Sign in to the same account on both.
2. In the Tailscale admin console → DNS: turn on **MagicDNS** and **HTTPS Certificates**.
3. On the Mac, with the stack running (`make up-detached`):

   ```sh
   tailscale serve --bg 8080
   tailscale serve status        # shows https://<mac-name>.<tailnet>.ts.net
   ```

   Use `serve`, never `funnel`: `funnel` publishes to the internet. If the `tailscale` command
   is missing with the App Store app, use
   `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.
4. Add that address to `.env` and restart, so realtime accepts it:

   ```sh
   PUBLIC_ORIGIN=https://<mac-name>.<tailnet>.ts.net
   make restart
   ```

5. On the iPhone, open the address in Safari and sign in. Then Share → **Add to Home Screen**.
6. Open **Muse** from the home screen → Status → **Enable notifications** → Allow →
   **Send test**. A "Test notification" should arrive within a few seconds.

## What leaves the Mac

- **Tailscale traffic** is end-to-end encrypted between your devices. Tailscale's coordination
  server sees device names and keys, not traffic. Self-hosting the control server
  (Headscale) removes that too.
- **A push** goes Mac → Apple (APNs) → iPhone. It carries only an encrypted notification id;
  the phone then fetches the text from the Mac over Tailscale. Apple sees that a push happened
  and its timing, never the content.
- **Approve / Deny** is a call from the app to the Mac over Tailscale. It never travels through
  a push service.

## Troubleshooting

- **Page loads but chat never updates**: `PUBLIC_ORIGIN` does not exactly match the address in
  the browser (scheme and host). Fix `.env`, then `make restart`.
- **No "Enable notifications" button**: open Muse from the home-screen icon, not a Safari tab.
  iOS allows push only for installed web apps (iOS 16.4+).
- **Test notification never arrives**: check iPhone Settings → Notifications → Muse, and Focus
  modes. The Mac needs internet access to reach Apple's push service.
- **Notifications stop after a while**: iOS drops a subscription when the app is deleted or
  notifications are turned off. Open the app → Status → Enable notifications again.
