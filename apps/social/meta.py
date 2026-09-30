"""Meta Graph API: connect a Facebook Page (and its Instagram account) and publish to them.

Docs: Facebook Login for Business, Pages API (/{page}/photos, /{page}/photo_stories)
and the Instagram Content Publishing API (/{ig-user}/media, /media_publish).
"""
import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SCOPES = ['pages_show_list', 'pages_read_engagement', 'pages_manage_posts', 'business_management',
          'instagram_basic', 'instagram_content_publish']


class MetaError(Exception):
    """A failure the user should see (Arabic). `expired` means the connection must be redone."""

    def __init__(self, message, expired=False):
        super().__init__(message)
        self.expired = expired


def _graph(path):
    return f'https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{path.lstrip("/")}'


def _call(method, path, **kwargs):
    try:
        response = requests.request(method, _graph(path), timeout=60, **kwargs)
    except requests.RequestException as exc:
        raise MetaError('تعذّر الوصول إلى خوادم Meta. تحقق من اتصال الخادم بالإنترنت.') from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or 'error' in body:
        error = body.get('error') or {}
        logger.warning('Meta API %s %s -> %s %s', method, path, response.status_code, error)
        if error.get('code') == 190:  # expired or revoked token
            raise MetaError('انتهت صلاحية ربط حساب Meta أو أُلغي. أعد ربط الحساب من صفحة «حسابات النشر».', expired=True)
        code = error.get('code') or 0
        if code == 10 or 200 <= code < 300:  # permission errors
            raise MetaError('لا يملك الحساب المربوط صلاحية النشر. أعد الربط ووافق على كل الصلاحيات المطلوبة.', expired=True)
        detail = error.get('error_user_msg') or error.get('message') or f'رمز {response.status_code}'
        raise MetaError(f'رفضت Meta الطلب: {detail}')
    return body


# --- Connecting -------------------------------------------------------------

def login_url(redirect_uri, state):
    params = {'client_id': settings.META_APP_ID, 'redirect_uri': redirect_uri, 'state': state,
              'scope': ','.join(SCOPES), 'response_type': 'code'}
    return f'https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{urlencode(params)}'


def pages_for_code(code, redirect_uri):
    """Exchange the login code for the user's Pages, each with a long-lived Page token and its Instagram account."""
    app = {'client_id': settings.META_APP_ID, 'client_secret': settings.META_APP_SECRET}
    short = _call('GET', 'oauth/access_token', params={**app, 'redirect_uri': redirect_uri, 'code': code})
    # Page tokens obtained with a long-lived user token don't expire.
    long = _call('GET', 'oauth/access_token', params={**app, 'grant_type': 'fb_exchange_token',
                                                      'fb_exchange_token': short['access_token']})
    pages = _call('GET', 'me/accounts', params={
        'access_token': long['access_token'], 'limit': 100,
        'fields': 'id,name,access_token,instagram_business_account{id,username}',
    })
    return [{
        'id': p['id'], 'name': p['name'], 'token': p['access_token'],
        'instagram': (p.get('instagram_business_account') or {}),
    } for p in pages.get('data', []) if p.get('access_token')]


# --- Publishing -------------------------------------------------------------

def publish_facebook(page_id, token, caption, image_path, story=False):
    """Post a photo to a Page (or a Page story). Returns the post id."""
    with open(image_path, 'rb') as f:
        if not story:
            body = _call('POST', f'{page_id}/photos', data={'message': caption, 'access_token': token},
                         files={'source': f})
            return body.get('post_id') or body['id']
        photo = _call('POST', f'{page_id}/photos', data={'published': 'false', 'access_token': token},
                      files={'source': f})
    body = _call('POST', f'{page_id}/photo_stories', data={'photo_id': photo['id'], 'access_token': token})
    return body.get('post_id') or body.get('id', '')


def publish_instagram(ig_id, token, caption, image_url, story=False, wait=30):
    """Publish an image (or story) to Instagram. Meta downloads the image from `image_url`, so it must be public."""
    params = {'image_url': image_url, 'access_token': token}
    if story:
        params['media_type'] = 'STORIES'
    else:
        params['caption'] = caption
    container = _call('POST', f'{ig_id}/media', data=params)['id']
    deadline = time.monotonic() + wait
    while True:
        status = _call('GET', container, params={'fields': 'status_code', 'access_token': token}).get('status_code')
        if status in (None, 'FINISHED'):
            break
        if status in ('ERROR', 'EXPIRED'):
            raise MetaError('لم يتمكن إنستغرام من تجهيز الصورة. تأكد أن رابط الموقع (SITE_URL) عام ويمكن الوصول إليه.')
        if time.monotonic() > deadline:
            raise MetaError('تأخر إنستغرام في تجهيز الصورة. حاول النشر مرة أخرى.')
        time.sleep(2)
    return _call('POST', f'{ig_id}/media_publish', data={'creation_id': container, 'access_token': token})['id']
