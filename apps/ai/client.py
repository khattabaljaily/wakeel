"""Thin wrapper around the AI provider used by every AI feature in Wakeel.

`call_json` asks for JSON matching a schema and turns every failure into an
AIError whose message is safe to show to the user. Two providers are
supported, picked by settings.AI_PROVIDER:

- 'anthropic': Claude with structured outputs (the schema is enforced by the API).
- 'deepseek': DeepSeek's OpenAI-compatible chat API in JSON mode. The schema is
  only described in the prompt, so the reply is checked here and the callers
  (apps.content.services) sanitise every field anyway.
"""
import json
import logging
from dataclasses import dataclass

import anthropic
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Claude models that support the server-side refusal fallback.
_FALLBACK_MODELS = ('claude-opus-5', 'claude-fable-5')


class AIError(Exception):
    """A failure the user should see (message is Arabic, user-facing)."""


@dataclass
class AIResult:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0


def call_json(system, prompt, schema, *, max_tokens=32000, effort='high'):
    if not settings.AI_ENABLED:
        raise AIError(f'لم يتم ضبط مفتاح الذكاء الاصطناعي بعد. أضف {settings.AI_KEY_NAME} إلى ملف secrets.json.')
    if settings.AI_PROVIDER == 'deepseek':
        return _deepseek(system, prompt, schema, max_tokens=max_tokens)
    return _anthropic(system, prompt, schema, max_tokens=max_tokens, effort=effort)


def _parse(text, request_id=''):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning('AI returned non-JSON output (request %s)', request_id)
        raise AIError('وصل رد غير مكتمل من خدمة الذكاء الاصطناعي. حاول مرة أخرى.') from exc
    if not isinstance(data, dict):
        raise AIError('وصل رد بصيغة غير متوقعة من خدمة الذكاء الاصطناعي. حاول مرة أخرى.')
    return data


# --- Claude -----------------------------------------------------------------

def _anthropic(system, prompt, schema, *, max_tokens, effort):
    model = settings.ANTHROPIC_MODEL
    kwargs = {
        'model': model,
        'max_tokens': max_tokens,
        'system': system,
        'messages': [{'role': 'user', 'content': prompt}],
        'output_config': {
            'effort': effort,
            'format': {'type': 'json_schema', 'schema': schema},
        },
    }
    if model.startswith(_FALLBACK_MODELS):
        # If the main model declines, the API retries on a fallback model in the same call.
        kwargs['betas'] = ['server-side-fallback-2026-07-01']
        kwargs['fallbacks'] = 'default'

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=900, max_retries=2)
    try:
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AIError('مفتاح Claude غير صالح. راجع ANTHROPIC_API_KEY في secrets.json.') from exc
    except anthropic.RateLimitError as exc:
        raise AIError('تم تجاوز حد الاستخدام المسموح لدى Claude مؤقتاً. حاول مرة أخرى بعد قليل.') from exc
    except anthropic.APIStatusError as exc:
        logger.exception('Claude API error %s', exc.status_code)
        raise AIError(f'تعذّر الاتصال بخدمة الذكاء الاصطناعي (رمز {exc.status_code}). حاول مرة أخرى.') from exc
    except anthropic.APIConnectionError as exc:
        raise AIError('تعذّر الوصول إلى خدمة الذكاء الاصطناعي. تحقق من اتصال الخادم بالإنترنت.') from exc

    usage = message.usage
    logger.info('Claude %s: in=%s out=%s stop=%s', message.model, usage.input_tokens, usage.output_tokens, message.stop_reason)

    if message.stop_reason == 'refusal':
        raise AIError('اعتذر النموذج عن تنفيذ هذا الطلب. عدّل التوجيهات وحاول مرة أخرى.')
    if message.stop_reason == 'max_tokens':
        raise AIError('كان الرد أطول من الحد المسموح. قلّل عدد المنشورات وحاول مرة أخرى.')

    text = ''.join(b.text for b in message.content if b.type == 'text')
    return AIResult(_parse(text, message._request_id), usage.input_tokens, usage.output_tokens)


# --- DeepSeek ---------------------------------------------------------------

_DEEPSEEK_ERRORS = {
    401: 'مفتاح DeepSeek غير صالح. راجع DEEPSEEK_API_KEY في secrets.json.',
    402: 'رصيد حساب DeepSeek غير كافٍ. اشحن الرصيد ثم حاول مرة أخرى.',
    429: 'تم تجاوز حد الاستخدام المسموح لدى DeepSeek مؤقتاً. حاول مرة أخرى بعد قليل.',
}


def _deepseek(system, prompt, schema, *, max_tokens):
    # JSON mode needs the word "json" in the prompt and a description of the shape.
    prompt = (
        f'{prompt}\n\nReply with one JSON object only, no other text. It must follow this JSON Schema exactly '
        f'(every required key present, strings may be empty):\n{json.dumps(schema, ensure_ascii=False)}'
    )
    payload = {
        'model': settings.DEEPSEEK_MODEL,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_object'},
        'max_tokens': max_tokens,
        'stream': False,
    }
    headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
    url = settings.DEEPSEEK_BASE_URL.rstrip('/') + '/chat/completions'

    # DeepSeek documents that JSON mode occasionally returns empty content; retry once.
    for attempt in range(2):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=900)
        except requests.RequestException as exc:
            raise AIError('تعذّر الوصول إلى خدمة الذكاء الاصطناعي. تحقق من اتصال الخادم بالإنترنت.') from exc
        if response.status_code != 200:
            logger.error('DeepSeek API error %s: %s', response.status_code, response.text[:500])
            raise AIError(_DEEPSEEK_ERRORS.get(
                response.status_code, f'تعذّر الاتصال بخدمة الذكاء الاصطناعي (رمز {response.status_code}). حاول مرة أخرى.'))

        body = response.json()
        choice = body['choices'][0]
        usage = body.get('usage', {})
        logger.info('DeepSeek %s: in=%s out=%s finish=%s', body.get('model'), usage.get('prompt_tokens'),
                    usage.get('completion_tokens'), choice.get('finish_reason'))
        if choice.get('finish_reason') == 'length':
            raise AIError('كان الرد أطول من الحد المسموح. قلّل عدد المنشورات وحاول مرة أخرى.')
        text = (choice.get('message') or {}).get('content') or ''
        if text.strip():
            break
        logger.warning('DeepSeek returned empty content (attempt %s)', attempt + 1)
    else:
        raise AIError('لم يصل رد من خدمة الذكاء الاصطناعي. حاول مرة أخرى.')

    data = _parse(text, body.get('id', ''))
    missing = [key for key in schema.get('required', []) if key not in data]
    if missing:
        logger.warning('DeepSeek reply is missing keys: %s', missing)
        raise AIError('وصل رد ناقص من خدمة الذكاء الاصطناعي. حاول مرة أخرى.')
    return AIResult(data, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))
