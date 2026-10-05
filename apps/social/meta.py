"""Meta Graph API: connect a Facebook Page (and its Instagram account) and publish to them.

Docs: Facebook Login for Business, Pages API (/{page}/photos, /{page}/photo_stories)
and the Instagram Content Publishing API (/{ig-user}/media, /media_publish).
"""
import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils.translation import gettext_lazy as _

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
        raise MetaError(_('تعذّر الوصول إلى خوادم Meta. تحقق من اتصال الخادم بالإنترنت.')) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or 'error' in body:
        error = body.get('error') or {}
        logger.warning('Meta API %s %s -> %s %s', method, path, response.status_code, error)
        if error.get('code') == 190:  # expired or revoked token
            raise MetaError(_('انتهت صلاحية ربط حساب Meta أو أُلغي. أعد ربط الحساب من صفحة «حسابات النشر».'), expired=True)
        code = error.get('code') or 0
        if code == 10 or 200 <= code < 300:  # permission errors
            raise MetaError(_('لا يملك الحساب المربوط صلاحية النشر. أعد الربط ووافق على كل الصلاحيات المطلوبة.'), expired=True)
        detail = error.get('error_user_msg') or error.get('message') or _('رمز %(code)s') % {'code': response.status_code}
        raise MetaError(_('رفضت Meta الطلب: %(detail)s') % {'detail': detail})
    return body


# --- Connecting -------------------------------------------------------------

def login_url(redirect_uri, state):
    scopes = list(dict.fromkeys([*SCOPES, *settings.META_INSIGHTS_SCOPES, *settings.META_INBOX_SCOPES, *settings.META_ADS_SCOPES]))
    params = {'client_id': settings.META_APP_ID, 'redirect_uri': redirect_uri, 'state': state,
              'scope': ','.join(scopes), 'response_type': 'code'}
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
        'user_token': long['access_token'],
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
            # Usually SITE_URL isn't public, so Instagram couldn't download the image.
            logger.error('Instagram container %s ended %s (image %s)', container, status, image_url)
            raise MetaError(_('لم يتمكن إنستغرام من تجهيز الصورة. حاول مرة أخرى لاحقاً، وإن تكرر ذلك تواصل مع الدعم.'))
        if time.monotonic() > deadline:
            raise MetaError(_('تأخر إنستغرام في تجهيز الصورة. حاول النشر مرة أخرى.'))
        time.sleep(2)
    return _call('POST', f'{ig_id}/media_publish', data={'creation_id': container, 'access_token': token})['id']


# --- Insights ---------------------------------------------------------------

def _total(value):
    """A Graph summary or number as an int."""
    if isinstance(value, dict):
        value = (value.get('summary') or {}).get('total_count', 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _lifetime(row):
    """A post insight's lifetime value: the entry without an end_time (the daily ones have one), else the last."""
    values = row.get('values') or []
    plain = [v for v in values if 'end_time' not in v]
    return (plain or values or [{}])[-1].get('value')


def facebook_post_stats(post_id, token):
    """Reach and engagement of a Page post, from the post's insights (pages_read_engagement + read_insights).

    Reading reactions and comments off the post object would need pages_read_user_content, so the
    counts come from the insights too. post_impressions_* were retired by Meta; reach is now the
    unique viewers of the post (post_total_media_view_unique).
    """
    data = _call('GET', f'{post_id}/insights', params={
        'access_token': token,
        'metric': 'post_total_media_view_unique,post_reactions_by_type_total,post_activity_by_action_type',
    })
    stats = {'likes': 0, 'comments': 0, 'shares': 0, 'saves': 0, 'reach': None}
    for row in data.get('data', []):
        if any('end_time' in v for v in row.get('values') or []):
            continue  # Meta also sends daily breakdowns of the same metric; the lifetime row is the total
        name, value = row.get('name'), _lifetime(row)
        if name == 'post_total_media_view_unique':
            stats['reach'] = _total(value)
        elif name == 'post_reactions_by_type_total' and isinstance(value, dict):
            stats['likes'] = sum(_total(v) for v in value.values())
        elif name == 'post_activity_by_action_type' and isinstance(value, dict):
            stats['comments'] = _total(value.get('comment'))
            stats['shares'] = _total(value.get('share'))
            stats['likes'] = stats['likes'] or _total(value.get('like'))
    return stats


def instagram_media_stats(media_id, token, story=False):
    """Likes, comments, shares, saves and reach of an Instagram post."""
    body = _call('GET', media_id, params={'access_token': token, 'fields': 'like_count,comments_count'})
    stats = {'likes': _total(body.get('like_count')), 'comments': _total(body.get('comments_count')),
             'shares': 0, 'saves': 0, 'reach': None}
    metrics = 'reach' if story else 'reach,shares,saved'
    try:
        data = _call('GET', f'{media_id}/insights', params={'access_token': token, 'metric': metrics})
        for row in data.get('data', []):
            value = _total((row.get('values') or [{}])[0].get('value', row.get('total_value', {}).get('value')))
            name = row.get('name')
            if name == 'reach':
                stats['reach'] = value
            elif name == 'shares':
                stats['shares'] = value
            elif name == 'saved':
                stats['saves'] = value
    except MetaError:
        logger.info('No insights for Instagram media %s', media_id)
    return stats


# --- Comments (inbox) -------------------------------------------------------

def facebook_comments(post_id, token):
    """Latest top-level comments on a Page post: [{id, author, author_id, text, time}]."""
    body = _call('GET', f'{post_id}/comments', params={
        'access_token': token, 'filter': 'toplevel', 'order': 'reverse_chronological', 'limit': 50,
        'fields': 'id,from{id,name},message,created_time',
    })
    return [{'id': c['id'], 'author': (c.get('from') or {}).get('name', ''), 'author_id': (c.get('from') or {}).get('id', ''),
             'text': c.get('message', ''), 'time': c.get('created_time')} for c in body.get('data', []) if c.get('id')]


def instagram_comments(media_id, token):
    body = _call('GET', f'{media_id}/comments', params={'access_token': token, 'limit': 50, 'fields': 'id,username,text,timestamp'})
    return [{'id': c['id'], 'author': c.get('username', ''), 'author_id': c.get('username', ''), 'text': c.get('text', ''),
             'time': c.get('timestamp')} for c in body.get('data', []) if c.get('id')]


def reply_facebook(comment_id, token, message):
    return _call('POST', f'{comment_id}/comments', data={'message': message, 'access_token': token}).get('id', '')


def reply_instagram(comment_id, token, message):
    return _call('POST', f'{comment_id}/replies', data={'message': message, 'access_token': token}).get('id', '')
