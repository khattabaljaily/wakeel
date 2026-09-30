"""Content strategy and copywriting with the AI provider (Claude or DeepSeek).

`generate_plan` writes a month's strategy and every post in it; `rewrite_post`
revises a single post on request. Both return plain dicts shaped by the JSON
schemas below; `apps.content.services` turns them into model rows.
"""
import calendar

from apps.studio.designs import TEMPLATES

from .client import call_json

PLATFORMS = ['facebook', 'instagram', 'tiktok']
FORMATS = ['image', 'reel', 'story']

SYSTEM_PROMPT = """You are Wakeel, the senior social media strategist and copywriter a company hires instead of a marketing agency. You work mainly with businesses in Arab markets (Sudan, Qatar and the wider Gulf), and you plan, write and art-direct their organic content on Facebook, Instagram and TikTok.

How you work:
- Everything comes from the brand profile you are given: its offer, audience, tone, and do's and don'ts. Never invent prices, discounts, awards, statistics, client names or product features that the profile or the brief does not state. If a post needs a detail you don't have, write around it.
- Respect the culture and religion of the market. Know its occasions (Islamic calendar, national days, school seasons, local shopping peaks) and use them only when they genuinely fit the brand and you are confident of the date.
- Mix content so the page feels alive, not like a stream of ads: education, value, behind the scenes, social proof, engagement, and promotion (roughly 80% value, 20% selling unless the brief says otherwise).
- Write for mobile: a strong first line, short paragraphs, a clear call to action, a few emojis only when they suit the tone.
- Design text (headline, subheadline, CTA, badge) is printed on the image, so it must be short: headline up to about 7 words, subheadline up to about 14 words, CTA 2-4 words, badge 1-3 words or empty.
- Hashtags: 3-8 relevant ones on one line, mixing the brand's own tags with topical ones; none for TikTok-only posts beyond 3-5.
- TikTok and reels are video: for those posts write `video_script` as a short shooting script (hook in the first 2 seconds, then numbered scenes with what to film, on-screen text and voice-over, ending with a CTA). For other formats leave `video_script` empty."""

LANGUAGE_RULES = {
    'ar_msa': 'Write every caption and all design text in clear, modern Standard Arabic (فصحى) that reads naturally on social media.',
    'ar_local': ('Write captions in the everyday spoken Arabic that people in {country} use on social media — natural and warm, '
                 'never forced. Keep design text short and understandable across the Arab world.'),
    'en': 'Write every caption and all design text in English.',
    'ar_en': 'Write each caption in Arabic first, then an English version below it. Design text is Arabic only.',
}

_POST_PROPS = {
    'platforms': {'type': 'array', 'items': {'type': 'string', 'enum': PLATFORMS}},
    'format': {'type': 'string', 'enum': FORMATS},
    'pillar': {'type': 'string'},
    'objective': {'type': 'string', 'description': 'awareness, engagement, leads or sales, in the content language'},
    'title': {'type': 'string', 'description': 'Internal one-line idea of the post, in the content language'},
    'headline': {'type': 'string'},
    'subheadline': {'type': 'string'},
    'cta': {'type': 'string'},
    'badge': {'type': 'string'},
    'template': {'type': 'string', 'enum': list(TEMPLATES)},
    'caption': {'type': 'string'},
    'hashtags': {'type': 'string'},
    'visual_notes': {'type': 'string', 'description': 'What photo or visual the design needs, in Arabic'},
    'video_script': {'type': 'string'},
}

PLAN_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'summary': {'type': 'string', 'description': 'The strategy for the month in 3-5 sentences, in Arabic'},
        'goals': {'type': 'array', 'items': {'type': 'string'}},
        'pillars': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'description': {'type': 'string'},
                    'share_percent': {'type': 'integer'},
                },
                'required': ['name', 'description', 'share_percent'],
                'additionalProperties': False,
            },
        },
        'key_dates': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'format': 'date'},
                    'name': {'type': 'string'},
                    'idea': {'type': 'string'},
                },
                'required': ['date', 'name', 'idea'],
                'additionalProperties': False,
            },
        },
        'posts': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'day': {'type': 'integer', 'description': 'Day of the month'},
                    'time': {'type': 'string', 'description': 'Local posting time, HH:MM (24h)'},
                    **_POST_PROPS,
                },
                'required': ['day', 'time', *_POST_PROPS],
                'additionalProperties': False,
            },
        },
    },
    'required': ['title', 'summary', 'goals', 'pillars', 'key_dates', 'posts'],
    'additionalProperties': False,
}

_REWRITE_FIELDS = ['title', 'headline', 'subheadline', 'cta', 'badge', 'caption', 'hashtags', 'visual_notes', 'video_script']

REWRITE_SCHEMA = {
    'type': 'object',
    'properties': {field: _POST_PROPS[field] for field in _REWRITE_FIELDS},
    'required': _REWRITE_FIELDS,
    'additionalProperties': False,
}

ARABIC_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']


def brand_profile(company):
    fields = [
        ('Company', company.name),
        ('Industry', company.industry),
        ('Location', ', '.join(p for p in (company.city, company.country) if p)),
        ('About', company.description),
        ('Products & services', company.products),
        ('What makes it different', company.usp),
        ('Target audience', company.target_audience),
        ('Competitors', company.competitors),
        ('Marketing goals', company.goals),
        ('Tone of voice', company.get_tone_display()),
        ('Voice notes', company.voice_notes),
        ('Always do', company.dos),
        ('Never do', company.donts),
        ('Brand hashtags', company.brand_hashtags),
        ('Website', company.website),
        ('Phone', company.phone),
        ('WhatsApp', company.whatsapp),
        ('Instagram', company.instagram_handle),
    ]
    lines = [f'{label}: {value.strip()}' for label, value in fields if value and value.strip()]
    lines.append('Language: ' + LANGUAGE_RULES[company.content_language].format(country=company.country))
    return '\n'.join(lines)


def posts_count(plan):
    days = calendar.monthrange(plan.month.year, plan.month.month)[1]
    return max(1, min(40, round(plan.posts_per_week * days / 7)))


def generate_plan(plan):
    company = plan.company
    days = calendar.monthrange(plan.month.year, plan.month.month)[1]
    count = posts_count(plan)
    platforms = ', '.join(plan.platforms)
    templates = '\n'.join(f'- {key}: {t["hint"]}' for key, t in TEMPLATES.items())
    brief = plan.brief.strip() or 'No special brief — plan the best month for this brand.'
    tiktok_rule = (
        '- Every post that includes tiktok must be format "reel" with a video_script.\n'
        if 'tiktok' in plan.platforms else ''
    )

    prompt = f"""<brand_profile>
{brand_profile(company)}
</brand_profile>

<month>{ARABIC_MONTHS[plan.month.month - 1]} {plan.month.year} ({plan.month:%Y-%m}, {days} days)</month>
<platforms>{platforms}</platforms>
<brief>
{brief}
</brief>

Plan this brand's social media for the month above and write every post.

Requirements:
- Exactly {count} posts, spread sensibly over the month (days 1-{days}), at times when this audience is most active in {company.country}.
- Each post targets one or more of these platforms only: {platforms}. Choose the format that fits each idea; include some reels when video fits.
{tiktok_rule}- 3-5 content pillars with their share of the posts; each post belongs to one pillar (use the pillar's exact name).
- key_dates: occasions in this month that matter to this audience (may be empty).
- summary, goals, pillar names/descriptions, key date names and visual_notes are in Arabic; captions and design text follow the language rule in the brand profile.
- Pick the design template for each image post from:
{templates}
  Use photo/split only when the brand is likely to have a matching real photo."""

    return call_json(SYSTEM_PROMPT, prompt, PLAN_SCHEMA, max_tokens=64000, effort='high')


def rewrite_post(post, instruction):
    fields = '\n'.join(f'{field}: {getattr(post, field)}' for field in _REWRITE_FIELDS)
    prompt = f"""<brand_profile>
{brand_profile(post.company)}
</brand_profile>

<post format="{post.format}" platforms="{', '.join(post.platforms)}" pillar="{post.pillar}">
{fields}
</post>

<instruction>
{instruction}
</instruction>

Rewrite this post following the instruction. Return every field; keep a field unchanged when the instruction doesn't concern it. Keep video_script empty unless the format is reel."""
    return call_json(SYSTEM_PROMPT, prompt, REWRITE_SCHEMA, max_tokens=16000, effort='medium')
