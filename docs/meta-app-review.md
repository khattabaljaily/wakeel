# Meta app review: Wakeel (Facebook + Instagram)

Code: `apps/social/meta.py` (login, publishing), `apps/social/views.py` (connect, disconnect), `apps/social/meta_callbacks.py`
(deauthorize and data deletion), `apps/insights`, `apps/inbox`, `apps/ads`, `apps/whatsapp`.
Scopes asked at login come from `SCOPES` in `meta.py` plus `META_INSIGHTS_SCOPES`, `META_INBOX_SCOPES`, `META_ADS_SCOPES` in `secrets.json`.

**Important:** Meta fails the whole login dialog when it asks for a permission the app hasn't added. Add a permission in the Meta
console (and have it approved or in Standard access for your own testers) **before** putting it in `secrets.json`.

## 0. Recommended order

Submit in batches; a rejection of one permission delays the whole submission.

| Batch | Permissions | Why first |
|---|---|---|
| 1 | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management` | The core product: publish approved posts. Everything else depends on it. |
| 2 | `read_insights`, `instagram_manage_insights` | Performance page (reach/saves). Engagement works without them. |
| 3 | `pages_read_user_content`, `pages_manage_engagement`, `instagram_manage_comments` | Comments inbox and replies. |
| 4 | `ads_management` | Paused promotion drafts. Hardest to get; needs a business case and Advanced Access. |
| 5 | WhatsApp Business (`whatsapp_business_messaging`, `whatsapp_business_management`) | Client approvals over WhatsApp. Separate product, template approval in WhatsApp Manager. |

## 1. Before submitting (app settings, developers.facebook.com → the app)

| Field | Value |
|---|---|
| App icon (1024x1024), name, category | filled in (category: Business and pages) |
| Privacy Policy URL | `https://wakeelservice.com/privacy/` (public, mentions Meta data and deletion) |
| Terms of Service URL | `https://wakeelservice.com/terms/` |
| User data deletion | **Data deletion request URL:** `https://wakeelservice.com/meta/data-deletion/` (the same URL answers Meta's POST and shows the instructions page to a person) |
| Deauthorize callback URL (Facebook Login → Settings) | `https://wakeelservice.com/meta/deauthorize/` |
| Valid OAuth Redirect URI (Facebook Login → Settings) | `https://wakeelservice.com/company/social/meta/callback/` |
| Business verification | Completed for the business that owns the app (Business Settings → Security Center). Required for Advanced Access to most permissions |
| App mode | Live after the review is approved; submit while in Development |
| App roles | Add the reviewer's test account as a Tester |
| `SITE_URL` in `secrets.json` on production | `https://wakeelservice.com` (https, public: Instagram downloads images from it) |

Checks to run first:

- [ ] Open `https://wakeelservice.com/meta/data-deletion/` signed out: the instructions page loads in Arabic and English.
- [ ] In the Meta console (Facebook Login → Settings) use the "test" buttons for the deauthorize and deletion callbacks if shown, or send a signed request: the response is 200 with `confirmation_code`.
- [ ] Accounts connected before this release have no saved Meta user id (`SocialAccount.meta_user_id` is empty), so a Facebook-side removal can't find them. **Reconnect your own test accounts** so the id is saved.
- [ ] A Facebook Page you admin, linked to an Instagram **professional** account, is ready as the demo target.

## 2. App description (paste)

> Wakeel is an AI marketing manager for businesses. It writes a monthly social media plan, writes every post and designs
> its image in the company's brand identity. The company's team reviews and approves each post inside Wakeel. Through
> Facebook Login, a Page admin connects their Facebook Page and its linked Instagram professional account, and Wakeel
> publishes the approved posts to them, either when the admin presses "Publish now" or at the scheduled time if the admin
> turned on automatic publishing. Wakeel only publishes what the team approved, only to the accounts the admin connected,
> and never uses Meta data for advertising or sells it. The admin can disconnect at any time in Wakeel or by removing the
> app in Facebook settings, and then we delete the tokens.

## 3. Why each permission is needed (paste per permission)

**Batch 1: publishing**

- `pages_show_list`: to list the Pages the admin manages, so they choose which Page to connect (`me/accounts`).
- `pages_read_engagement`: to read the Page's name/ID and the basic engagement counts of the posts Wakeel published, shown on the post.
- `pages_manage_posts`: to publish the approved photo post (image and caption) and Page stories to the connected Page.
- `business_management`: to read the Pages and Instagram accounts of a Business Portfolio the admin manages, because many Pages are owned by a business and not by the person's profile.
- `instagram_basic`: to read the connected Instagram professional account's ID and username, shown in Wakeel so the team knows which account is connected.
- `instagram_content_publish`: to publish the approved image post or story to the connected Instagram professional account.

**Batch 2: insights**

- `read_insights`: to show the reach and impressions of posts Wakeel published, on the Performance page, so the team learns what works.
- `instagram_manage_insights`: the same for Instagram posts (reach, saves, shares).

**Batch 3: comments inbox**

- `pages_read_user_content`: to read comments on the Page posts Wakeel published (last 30 days) and show them in the Inbox with an AI-suggested reply.
- `pages_manage_engagement`: to send the reply the team approved (or, if the admin turns auto-reply on, simple thanks/answers) to a comment on the Page.
- `instagram_manage_comments`: the same for comments on the Instagram posts Wakeel published.

**Batch 4: ads**

- `ads_management`: after the admin picks one of their own ad accounts, to create a small test promotion (campaign, ad set, ad) for a published post. Everything is created **PAUSED**, with a budget capped at 500/day for 30 days; nothing is spent until the admin turns it on in Ads Manager.

**Batch 5: WhatsApp** (separate product)

- `whatsapp_business_messaging`: to send the company's own client the approved review message and the posts awaiting review, with Approve / Request changes buttons. Only the client number the company entered is messaged.
- `whatsapp_business_management`: to manage the review message template.

Wakeel does not read private messages, friends, followers lists, or anything not listed above.

## 4. Screencast (one per permission; English or captioned; real production domain, URL bar visible)

Use a Page you admin + a linked Instagram professional account + a tester user. Keep recordings 1–3 minutes, no cuts in the Meta dialog.

**Batch 1 (record one video, reuse for every permission in it)**

1. Show `https://wakeelservice.com` and sign in to Wakeel.
2. Company → Publishing accounts → **Connect Facebook**. Show Meta's dialog with **all requested permissions listed**; press Continue.
3. Choose the Page. Wakeel shows the connected Page and the Instagram account's username (`pages_show_list`, `instagram_basic`, `business_management`).
4. Open an approved post: show the design, caption and platforms. Press **Publish now**.
5. Open the Facebook Page and show the post live (`pages_manage_posts`); open Instagram and show the post (`instagram_content_publish`).
6. Back in Wakeel show the post marked as published with its link and counts (`pages_read_engagement`).
7. Disconnect the account in Wakeel and show it is gone. (Optional second clip: remove the app in Facebook → Settings → Business integrations; reload Wakeel and show the connection is gone: this proves the deauthorize callback.)

**Batch 2** Performance page: connect with the insights permissions, open Performance, show reach/saves of published posts and press **Refresh**.

**Batch 3** Inbox: comment on a published post from another account; wait for (or trigger) the read; show the comment with sentiment and the drafted reply; edit and send the reply; show it live on Facebook/Instagram.

**Batch 4** Ads: open a published post → Promote; show the suggestion, pick the ad account, create; open Ads Manager and show the campaign **Paused**.

**Batch 5** Plan page → Send to the client on WhatsApp; show the message and the buttons on the phone, tap Approve, show the post approved in Wakeel.

## 5. Test instructions for the reviewer (paste in "Notes")

1. Go to `https://wakeelservice.com` and sign in with the review account (put the credentials here, a Wakeel account created for Meta with one company and one approved post; do not reuse a real customer's account).
2. Company → Publishing accounts → Connect Facebook. Sign in to Facebook with your test user (added as a Tester), accept the permissions, choose the Page.
3. Open the "Review account" company's approved post and press **Publish now**. The post appears on the Page and on the linked Instagram account.
4. To remove access: Publishing accounts → Disconnect, or remove Wakeel in Facebook settings.

## 6. Common rejection reasons to check

- Screencast doesn't show the permission being **used** end to end (publish, then the post live on the platform).
- Login dialog in the video doesn't list all permissions that are requested. Re-record from the real dialog.
- Privacy Policy doesn't mention what is read per permission (it now does: Meta user id, comments and insights when enabled).
- Business verification not completed (Advanced Access needs it).
- Demo account can't log in, or the Page isn't linked to an Instagram professional account.
- A permission is requested but not actually used by the product. Only submit permissions the feature behind it is on for.


## While the app is under review: "coming soon" for the public (2026-11-19)

Connecting Facebook/Instagram shows "coming soon" to every company except the system admins and the e-mails in `META_PREVIEW_EMAILS` (`secrets.json`, a list). TikTok stays open. **Put the reviewer's Wakeel login (the account named in "Test instructions for the reviewer", section 5) in `META_PREVIEW_EMAILS`, or Meta's reviewer will see "coming soon" instead of the flow and the review will fail.** Companies already connected keep working.

When Meta approves the app: add `"META_PUBLIC": true` to `secrets.json` and restart `wakeel`; every company can then connect. (Code: `meta_open()` in `apps/social/views.py`; tests: `apps/social/test_meta_gate.py`.)
