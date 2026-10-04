# TikTok app review: preparing Wakeel to leave the sandbox

Wakeel uses **Login Kit** and the **Content Posting API** in inbox mode (`post_mode=MEDIA_UPLOAD`, scope `video.upload`).
Photo designs are sent to the creator's TikTok inbox; nothing is published until the creator presses "Post" in the TikTok app.
Code: `apps/social/tiktok.py`, `apps/social/views.py` (connect, callback, disconnect), `apps/social/services.py` (sending).

## 1. App settings (developers.tiktok.com → Manage apps)

| Field | Value |
|---|---|
| Platform | Web |
| Website URL | `SITE_URL` (the production domain) |
| Terms of Service URL | `SITE_URL/terms/` |
| Privacy Policy URL | `SITE_URL/privacy/` |
| Redirect URI (Login Kit) | `SITE_URL/company/social/tiktok/callback/` (https, exact match) |
| Products | Login Kit, Content Posting API |
| Scopes | `user.info.basic`, `video.upload` |
| URL prefix for PULL_FROM_URL | `SITE_URL/media/publish/` (verify it: signature file or DNS TXT record, as TikTok asks) |

## 2. App description (paste)

> Wakeel is an AI marketing manager for businesses. It writes a monthly social media plan, writes every post and designs its
> image in the company's brand identity. The team reviews and approves each post. Through Login Kit a company connects its
> TikTok account, and through the Content Posting API Wakeel sends the approved photo post (image, title, caption) to the
> creator's TikTok inbox. The creator opens the TikTok app and finishes and publishes the post themselves.

## 3. Why each scope is needed (paste)

- `user.info.basic`: to read the connected creator's `open_id` and display name, shown in Wakeel so the team knows which account is connected.
- `video.upload`: to send approved photo posts to the creator's TikTok inbox (`post_mode=MEDIA_UPLOAD`) for them to review and post.

Wakeel does not read videos, followers, messages or analytics, and does not post on its own: the creator always completes the post in TikTok.

## 4. Demo video checklist (screen recording, English or captioned)

Record in the sandbox with a sandbox target user, on the real production domain, showing the whole flow:

1. Wakeel sign-in, then Company → Publishing accounts → **Connect TikTok** (the wizard page).
2. TikTok's authorization screen, with the URL bar visible and both scopes listed; tap Authorize.
3. Back in Wakeel: the connected account's display name appears.
4. Open an approved post (TikTok selected), show the design, title and caption, press **Publish now**.
5. Wakeel shows the post as sent; open the TikTok app and show the notification in the inbox, and finish the post there.
6. Disconnect the account in Wakeel (this now revokes the token at TikTok through `oauth/revoke/`), and show it is gone.

## 5. Before submitting

- [ ] Redirect URI and URL prefix are verified in the TikTok console, and `SITE_URL` in `secrets.json` on production is the same https domain.
- [ ] The sandbox account's target user can connect and receive a post in the inbox (a real end-to-end run: it can't be done from local development, which has no https redirect).
- [ ] Terms and privacy pages are public without login and mention TikTok data (they do, see `templates/core/legal/`).
- [ ] App icon (1024x1024), name and category are filled in.
- [ ] Demo video recorded as in section 4.
- [ ] Keep `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` in `secrets.json` only. If the console shows different credentials for sandbox and production, update both values on the production server after approval.
