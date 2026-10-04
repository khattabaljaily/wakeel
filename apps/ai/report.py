"""Write the narrative of a monthly performance report from real numbers."""
import json

from .client import call_json
from .planner import brand_profile

REPORT_SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {'type': 'string', 'description': '3-5 sentences: how the month went, in plain words'},
        'wins': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Up to 3 things that worked'},
        'recommendations': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Exactly 3 concrete actions for next month'},
    },
    'required': ['summary', 'wins', 'recommendations'],
    'additionalProperties': False,
}

SYSTEM_PROMPT = """You are Wakeel, the social media manager who reports to the brand's owner each month. You are given the brand profile and the real numbers of the month (reach, interactions, which posts, pillars, layouts and hours did best). Write the report the owner reads.

Rules:
- Use only the numbers you are given. Never invent figures, causes you cannot see, or benchmarks. If the data is thin (few posts, no reach), say so plainly instead of drawing big conclusions.
- Be specific: name the best posts and pillars, compare with the weaker ones, and say what to do about it.
- Recommendations are three concrete actions for next month (content to do more of, to drop, timing, format), each one sentence, tied to the numbers.
- Write in {language}. Plain, warm and direct, no marketing fluff."""


def write_report(company, month_label, stats, language='Arabic (Modern Standard Arabic)'):
    """Returns an AIResult with summary, wins and recommendations. `stats` is apps.insights.services.summarize()."""
    prompt = f"""<brand_profile>
{brand_profile(company)}
</brand_profile>

<month>{month_label}</month>
<results>
{json.dumps(stats, ensure_ascii=False, default=str, indent=1)}
</results>

Write the monthly report."""
    return call_json(SYSTEM_PROMPT.format(language=language), prompt, REPORT_SCHEMA, max_tokens=4000, effort='medium')
