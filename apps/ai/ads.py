"""Suggest how to promote a post that did well: budget, length and audience."""
from .client import call_json
from .planner import brand_profile

SCHEMA = {
    'type': 'object',
    'properties': {
        'daily_budget': {'type': 'number', 'description': 'In the ad account currency'},
        'days': {'type': 'integer'},
        'age_min': {'type': 'integer'},
        'age_max': {'type': 'integer'},
        'gender': {'type': 'string', 'enum': ['all', 'male', 'female']},
        'rationale': {'type': 'string', 'description': 'Why this post and this setup, 2-3 sentences'},
        'audience_notes': {'type': 'string', 'description': 'Interests and behaviours to add by hand in Ads Manager'},
    },
    'required': ['daily_budget', 'days', 'age_min', 'age_max', 'gender', 'rationale', 'audience_notes'],
    'additionalProperties': False,
}

SYSTEM_PROMPT = """You are Wakeel, the brand's social media manager, advising a small business on boosting one organic post that did well. Be careful with the client's money: suggest a modest test budget (the smallest that gives a useful result, for a few days) and a clear audience from the brand profile. Never promise results. Write the rationale and notes in {language}."""


def suggest(company, post, stats, currency, language='Arabic (Modern Standard Arabic)'):
    prompt = f"""<brand_profile>
{brand_profile(company)}
</brand_profile>

<post title="{post.title}" pillar="{post.pillar}">
{post.full_caption[:1500]}
</post>
<organic_results>{stats}</organic_results>
<currency>{currency}</currency>

Suggest a paid promotion of this post (engagement objective)."""
    return call_json(SYSTEM_PROMPT.format(language=language), prompt, SCHEMA, max_tokens=3000, effort='low')
