"""What an AI call costs, in USD.

DeepSeek prices depend on the model, on whether input tokens hit the context
cache, and on the time of the call (peak / off-peak), so the cost is worked
out when the call is made and stored on the job. Other models (Claude) use
the flat AI_PRICE_* settings when they are set.
"""
import datetime

from django.conf import settings

MTOK = 1_000_000

# USD per million tokens as (off-peak, peak), from DeepSeek's pricing page.
DEEPSEEK_PRICES = {
    'flash': {'cache_hit': (0.003, 0.006), 'cache_miss': (0.15, 0.30), 'output': (0.60, 1.20)},  # DeepSeek-V4.1-Flash
    'pro': {'cache_hit': (0.022, 0.044), 'cache_miss': (0.66, 1.32), 'output': (1.98, 3.96)},  # DeepSeek-V4-Pro-0813
}


def deepseek_tier(model):
    model = (model or '').lower()
    if 'deepseek' not in model:
        return None
    return 'flash' if 'flash' in model else 'pro' if 'pro' in model else None


def _minutes(hhmm):
    hours, minutes = str(hhmm).split(':')
    return int(hours) * 60 + int(minutes)


def is_off_peak(when):
    """Whether `when` falls in DeepSeek's off-peak window (DEEPSEEK_OFF_PEAK_UTC, which may cross midnight)."""
    start, end = (_minutes(t) for t in settings.DEEPSEEK_OFF_PEAK_UTC)
    utc = when.astimezone(datetime.timezone.utc)
    now = utc.hour * 60 + utc.minute
    return start <= now < end if start < end else now >= start or now < end


def cost(model, input_tokens, cache_hit_tokens, output_tokens, when):
    """USD for one call, or None when the model's prices aren't known. input_tokens includes the cache hits."""
    tier = deepseek_tier(model)
    if tier:
        prices = DEEPSEEK_PRICES[tier]
        slot = 0 if is_off_peak(when) else 1
        miss = max(input_tokens - cache_hit_tokens, 0)
        return (cache_hit_tokens * prices['cache_hit'][slot] + miss * prices['cache_miss'][slot]
                + output_tokens * prices['output'][slot]) / MTOK
    if settings.AI_PRICE_INPUT_PER_MTOK or settings.AI_PRICE_OUTPUT_PER_MTOK:
        return (input_tokens * settings.AI_PRICE_INPUT_PER_MTOK + output_tokens * settings.AI_PRICE_OUTPUT_PER_MTOK) / MTOK
    return None
