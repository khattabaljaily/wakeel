# Meta console: paste sheet (Wakeel)

Open https://developers.facebook.com/apps → Wakeel app. Do the steps in order.

## A. App settings → Basic
- Privacy Policy URL: https://wakeelservice.com/privacy/
- Terms of Service URL: https://wakeelservice.com/terms/
- User data deletion → Data deletion request URL: https://wakeelservice.com/meta/data-deletion/
- App icon 1024x1024, category: Business and pages
- App domains: wakeelservice.com

## B. Facebook Login → Settings
- Valid OAuth Redirect URIs: https://wakeelservice.com/company/social/meta/callback/
- Deauthorize callback URL: https://wakeelservice.com/meta/deauthorize/
- Client OAuth login: on; Web OAuth login: on

## C. App roles → Roles
- Add the reviewer/test Facebook user as Tester.

## D. Business Settings → Security Center → Business verification
- Complete it (company documents); required for Advanced Access.

## E. App review → Permissions and features (batch 1 first)
Request Advanced Access for: pages_show_list, pages_read_engagement, pages_manage_posts, business_management, instagram_basic, instagram_content_publish.
For each, paste its line from section F and upload the screencast (batch 1 video).

## F. Why each permission
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

## G. App description (Settings → Basic → or review "Describe your app")
> Wakeel is an AI marketing manager for businesses. It writes a monthly social media plan, writes every post and designs
> its image in the company's brand identity. The company's team reviews and approves each post inside Wakeel. Through
> Facebook Login, a Page admin connects their Facebook Page and its linked Instagram professional account, and Wakeel
> publishes the approved posts to them, either when the admin presses "Publish now" or at the scheduled time if the admin
> turned on automatic publishing. Wakeel only publishes what the team approved, only to the accounts the admin connected,
> and never uses Meta data for advertising or sells it. The admin can disconnect at any time in Wakeel or by removing the
> app in Facebook settings, and then we delete the tokens.

## H. Notes for the reviewer
1. Go to `https://wakeelservice.com` and sign in with the review account (put the credentials here, a Wakeel account created for Meta with one company and one approved post; do not reuse a real customer's account).
2. Company → Publishing accounts → Connect Facebook. Sign in to Facebook with your test user (added as a Tester), accept the permissions, choose the Page.
3. Open the "Review account" company's approved post and press **Publish now**. The post appears on the Page and on the linked Instagram account.
4. To remove access: Publishing accounts → Disconnect, or remove Wakeel in Facebook settings.

## I. Before pressing Submit
- [ ] Reconnect your test Facebook account in Wakeel (saves the Meta user id)
- [ ] Video shows Meta's dialog listing every permission requested
- [ ] Reviewer account credentials filled in section H
- [ ] https://wakeelservice.com/meta/data-deletion/ opens signed out
