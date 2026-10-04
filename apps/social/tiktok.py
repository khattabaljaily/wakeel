"""TikTok: connect an account (Login Kit) and send photo posts to its TikTok inbox (Content Posting API).

Wakeel uses the inbox flow (post_mode MEDIA_UPLOAD, scope video.upload): TikTok downloads the design and
notifies the creator, who finishes the post in the app. Unlike direct posting it needs no TikTok audit to be public.
Docs: Login Kit for Web, Manage User Access Tokens, Content Posting API (photo post, get post status).
"""
import datetime
import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

API = 'https://open.tiktokapis.com/v2/'
SCOPES = ['user.info.basic', 'video.upload']


class TikTokError(Exception):
    """A failure the user should see. `expired` means the account must be connected again."""

    def __init__(self, message, expired=False):
        super().__init__(message)
        self.expired = expired


def _request(method, path, **kwargs):
    try:
        response = requests.request(method, API + path, timeout=60, **kwargs)
    except requests.RequestException as exc:
        raise TikTokError(_('تعذّر الوصول إلى خوادم تيك توك. تحقق من اتصال الخادم بالإنترنت.')) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    # OAuth calls answer {"error": "...", "error_description": ...}; the others {"data": ..., "error": {"code": "ok"}}.
    error = body.get('error')
    if isinstance(error, dict):
        code, detail = error.get('code', 'ok'), error.get('message')
    else:
        code, detail = error or 'ok', body.get('error_description')
    if response.status_code >= 400 or code != 'ok':
        logger.warning('TikTok API %s %s -> %s %s %s', method, path, response.status_code, code, detail)
        if code in ('access_token_invalid', 'invalid_grant', 'scope_not_authorized'):
            raise TikTokError(_('انتهت صلاحية ربط تيك توك أو أُلغي. أعد ربط الحساب من «حسابات النشر».'), expired=True)
        raise TikTokError(_('رفض تيك توك الطلب: %(detail)s') % {'detail': detail or code or response.status_code})
    return body


# --- Connecting -------------------------------------------------------------

def login_url(redirect_uri, state):
    params = {'client_key': settings.TIKTOK_CLIENT_KEY, 'scope': ','.join(SCOPES), 'response_type': 'code',
              'redirect_uri': redirect_uri, 'state': state}
    return f'https://www.tiktok.com/v2/auth/authorize/?{urlencode(params)}'


def _token_fields(body):
    now = timezone.now()
    return {'access_token': body['access_token'], 'refresh_token': body.get('refresh_token', ''),
            'token_expires_at': now + datetime.timedelta(seconds=int(body.get('expires_in') or 86400))}


def account_for_code(code, redirect_uri):
    """Exchange the login code for tokens and the creator's name. Returns the SocialAccount fields."""
    body = _request('POST', 'oauth/token/', data={
        'client_key': settings.TIKTOK_CLIENT_KEY, 'client_secret': settings.TIKTOK_CLIENT_SECRET,
        'code': code, 'grant_type': 'authorization_code', 'redirect_uri': redirect_uri,
    })
    if 'video.upload' not in (body.get('scope') or '').split(','):
        raise TikTokError(_('لم تُمنح صلاحية إرسال المنشورات إلى تيك توك. أعد الربط ووافق على كل الصلاحيات.'))
    fields = _token_fields(body)
    user = _request('GET', 'user/info/', params={'fields': 'open_id,display_name'},
                    headers={'Authorization': f'Bearer {fields["access_token"]}'})
    info = (user.get('data') or {}).get('user') or {}
    return {**fields, 'external_id': body.get('open_id') or info.get('open_id', ''),
            'name': info.get('display_name') or 'TikTok'}


def fresh_token(account):
    """The account's access token, renewed first when it is about to expire (they last 24 hours)."""
    if account.token_expires_at and account.token_expires_at > timezone.now() + datetime.timedelta(minutes=5):
        return account.access_token
    body = _request('POST', 'oauth/token/', data={
        'client_key': settings.TIKTOK_CLIENT_KEY, 'client_secret': settings.TIKTOK_CLIENT_SECRET,
        'grant_type': 'refresh_token', 'refresh_token': account.refresh_token,
    })
    for name, value in _token_fields(body).items():
        if value:
            setattr(account, name, value)
    account.save(update_fields=['access_token', 'refresh_token', 'token_expires_at'])
    return account.access_token


def revoke(account):
    """Withdraw Wakeel's access on TikTok's side when the account is disconnected. Best effort: never blocks the disconnect."""
    try:
        _request('POST', 'oauth/revoke/', data={'client_key': settings.TIKTOK_CLIENT_KEY,
                                                'client_secret': settings.TIKTOK_CLIENT_SECRET, 'token': account.access_token})
    except TikTokError:
        logger.info('TikTok token of %s was already invalid; nothing to revoke', account.external_id)


# --- Sending ----------------------------------------------------------------

def send_photo(token, image_url, title, description, wait=60):
    """Send one image to the creator's TikTok inbox. Returns the publish id once TikTok has fetched the image.

    TikTok downloads `image_url` (a JPEG under a URL prefix verified in the TikTok app settings), so the
    caller must keep the file until this returns.
    """
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=UTF-8'}
    body = _request('POST', 'post/publish/content/init/', headers=headers, json={
        'media_type': 'PHOTO', 'post_mode': 'MEDIA_UPLOAD',
        'post_info': {'title': title[:90], 'description': description[:4000]},
        'source_info': {'source': 'PULL_FROM_URL', 'photo_images': [image_url], 'photo_cover_index': 0},
    })
    publish_id = body['data']['publish_id']
    deadline = time.monotonic() + wait
    while True:
        data = _request('POST', 'post/publish/status/fetch/', headers=headers, json={'publish_id': publish_id})['data']
        status = data.get('status')
        if status in ('SEND_TO_USER_INBOX', 'PUBLISH_COMPLETE'):
            return publish_id
        if status == 'FAILED':
            logger.error('TikTok post %s failed: %s (image %s)', publish_id, data.get('fail_reason'), image_url)
            if data.get('fail_reason') == 'auth_removed':
                raise TikTokError(_('أُلغي ربط تيك توك من التطبيق. أعد ربط الحساب من «حسابات النشر».'), expired=True)
            raise TikTokError(_('لم يتمكن تيك توك من استلام الصورة (%(reason)s). حاول مرة أخرى لاحقاً، وإن تكرر ذلك تواصل مع الدعم.')
                              % {'reason': data.get('fail_reason') or '?'})
        if time.monotonic() > deadline:
            raise TikTokError(_('تأخر تيك توك في استلام الصورة. حاول الإرسال مرة أخرى.'))
        time.sleep(2)
