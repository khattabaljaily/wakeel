"""Which background jobs are paid, and what they cost: the bridge between `jobs.Job` and the price list."""
from . import quote as quotes

# Job kind -> price-list service. A kind that is not here has no AI in it (rendering, publishing, numbers) and is free.
SERVICES = {
    'generate_plan': 'generate_plan',
    'rewrite_post': 'rewrite_post',
    'variant_post': 'variant_post',
    'repost': 'repost',
    'generate_report': 'generate_report',
    'competitors': 'competitors',
    'ad_suggest': 'ad_suggest',
    'learn': 'learn',
    'fetch_inbox': 'fetch_inbox',
}


def units_for(kind, company, params):
    """The units a job's price grows with: the posts of a plan."""
    if kind == 'generate_plan' and params.get('plan_id'):
        from apps.ai.planner import posts_count
        from apps.content.models import ContentPlan
        plan = ContentPlan.objects.filter(pk=params['plan_id'], company=company).first()
        return posts_count(plan) if plan else None
    return None


def quote_for(kind, company, params=None):
    """The itemised quote of a job kind, or None when the kind is free of AI."""
    service = SERVICES.get(kind)
    if service is None:
        return None
    return quotes.make(service, units_for(kind, company, params or {}))


def expected_points(data):
    """The total the person was shown, posted back with the action (None when the client did not send one)."""
    value = (data.get('expected_points') if hasattr(data, 'get') else None)
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def price_table(service_key, upto=None):
    """{units: points} for a service priced by units: the screen works the price out from this table, the charge from the
    same function, and the two are compared at the charge."""
    from . import catalog
    return {n: catalog.price_points(service_key, n) for n in range(1, (upto or catalog.max_units(service_key)) + 1)}
