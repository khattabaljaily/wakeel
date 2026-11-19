from unittest import mock

from django.test import SimpleTestCase, override_settings

from .client import AIError, call_json

SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'required': ['a'], 'additionalProperties': False}


def reply(content, finish='stop', status=200):
    response = mock.Mock(status_code=status, text='')
    response.json.return_value = {
        'id': 'x', 'model': 'deepseek-v4-pro',
        'choices': [{'message': {'content': content}, 'finish_reason': finish}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 6},
    }
    return response


@override_settings(AI_PROVIDER='deepseek', AI_ENABLED=True, DEEPSEEK_API_KEY='k', ANTHROPIC_API_KEY='', DEEPSEEK_MODEL='deepseek-v4-pro',
                   DEEPSEEK_BASE_URL='https://api.deepseek.com')
class DeepSeekTests(SimpleTestCase):
    @mock.patch('apps.ai.client.requests.post')
    def test_json_mode_request_and_usage(self, post):
        post.return_value = reply('{"a": "ب"}')
        result = call_json('system', 'prompt', SCHEMA)
        self.assertEqual(result.data, {'a': 'ب'})
        self.assertEqual((result.input_tokens, result.output_tokens, result.cache_hit_tokens), (10, 20, 4))
        self.assertEqual(result.model, 'deepseek-v4-pro')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertIn('JSON', payload['messages'][1]['content'])
        self.assertEqual(post.call_args.args[0], 'https://api.deepseek.com/chat/completions')

    @mock.patch('apps.ai.client.requests.post')
    def test_retries_empty_content_once(self, post):
        post.side_effect = [reply(''), reply('{"a": ""}')]
        self.assertEqual(call_json('s', 'p', SCHEMA).data, {'a': ''})
        self.assertEqual(post.call_count, 2)

    @mock.patch('apps.ai.client.requests.post')
    def test_errors_are_user_facing(self, post):
        post.return_value = reply('{}', status=402)
        with self.assertRaises(AIError) as caught:
            call_json('s', 'p', SCHEMA)
        # The subscriber sees a plain message; the provider and the cause are kept for the admin panel.
        self.assertIn('غير متاحة حالياً', str(caught.exception))
        self.assertNotIn('DeepSeek', str(caught.exception))
        self.assertIn('balance', caught.exception.detail)
        post.return_value = reply('{"a": "x', finish='length')
        with self.assertRaisesMessage(AIError, 'أطول'):
            call_json('s', 'p', SCHEMA)
        post.return_value = reply('{"b": 1}')
        with self.assertRaisesMessage(AIError, 'ناقص'):
            call_json('s', 'p', SCHEMA)


TIERS = {'interactive': ['anthropic', 'claude-sonnet-5-5'], 'background': ['deepseek', 'deepseek-v4-pro'],
         'premium': ['anthropic', 'claude-opus-5-5']}


def claude_answer(model='claude-sonnet-5-5'):
    from .client import AIResult
    return AIResult({'a': 'من Claude'}, 100, 50, 0, model)


@override_settings(AI_ENABLED=True, AI_TIERS=TIERS, ANTHROPIC_MODEL_FAST='claude-sonnet-5-5', ANTHROPIC_MODEL='claude-opus-5-5',
                   DEEPSEEK_MODEL='deepseek-v4-pro', DEEPSEEK_BASE_URL='https://api.deepseek.com')
class RoutingTests(SimpleTestCase):
    """Each call goes to the model its tier names; a missing key falls back to the other provider; a weak DeepSeek answer
    is repeated on Claude."""

    @override_settings(ANTHROPIC_API_KEY='a', DEEPSEEK_API_KEY='d')
    @mock.patch('apps.ai.client.requests.post')
    @mock.patch('apps.ai.client._anthropic')
    def test_tiers_pick_their_models(self, anthropic, post):
        anthropic.return_value = claude_answer()
        post.return_value = reply('{"a": "ب"}')
        call_json('s', 'p', SCHEMA)                                   # interactive is the default
        self.assertEqual(anthropic.call_args.kwargs['model'], 'claude-sonnet-5-5')
        call_json('s', 'p', SCHEMA, tier='premium')
        self.assertEqual(anthropic.call_args.kwargs['model'], 'claude-opus-5-5')
        self.assertEqual(anthropic.call_count, 2)
        self.assertEqual(call_json('s', 'p', SCHEMA, tier='background').model, 'deepseek-v4-pro')
        self.assertEqual(post.call_count, 1)

    @override_settings(ANTHROPIC_API_KEY='', DEEPSEEK_API_KEY='d')
    @mock.patch('apps.ai.client.requests.post')
    def test_without_a_claude_key_everything_runs_on_deepseek(self, post):
        post.return_value = reply('{"a": "ب"}')
        for tier in ('interactive', 'background', 'premium'):
            self.assertEqual(call_json('s', 'p', SCHEMA, tier=tier).model, 'deepseek-v4-pro')

    @override_settings(ANTHROPIC_API_KEY='a', DEEPSEEK_API_KEY='')
    @mock.patch('apps.ai.client._anthropic')
    def test_without_a_deepseek_key_background_runs_on_claude(self, anthropic):
        anthropic.return_value = claude_answer()
        call_json('s', 'p', SCHEMA, tier='background')
        self.assertEqual(anthropic.call_args.kwargs['model'], 'claude-sonnet-5-5')

    @override_settings(ANTHROPIC_API_KEY='', DEEPSEEK_API_KEY='')
    def test_no_key_at_all_is_unavailable(self):
        with override_settings(AI_ENABLED=False), self.assertRaises(AIError):
            call_json('s', 'p', SCHEMA)
        from .client import resolve
        with self.assertRaises(AIError):
            resolve('interactive')

    @override_settings(ANTHROPIC_API_KEY='a', DEEPSEEK_API_KEY='d')
    @mock.patch('apps.ai.client.requests.post')
    @mock.patch('apps.ai.client._anthropic')
    def test_a_weak_deepseek_answer_is_repeated_on_claude(self, anthropic, post):
        anthropic.return_value = claude_answer()
        for weak in (reply('{"b": 1}'), reply('{"a": "x', finish='length')):
            post.return_value = weak
            result = call_json('s', 'p', SCHEMA, tier='background')
            self.assertEqual((result.data, result.model), ({'a': 'من Claude'}, 'claude-sonnet-5-5'))
        self.assertEqual(anthropic.call_count, 2)

    @override_settings(ANTHROPIC_API_KEY='a', DEEPSEEK_API_KEY='d')
    @mock.patch('apps.ai.client.requests.post')
    @mock.patch('apps.ai.client._anthropic')
    def test_failures_a_second_model_cannot_fix_are_not_repeated(self, anthropic, post):
        post.return_value = reply('{}', status=429)
        with self.assertRaises(AIError):
            call_json('s', 'p', SCHEMA, tier='background')
        anthropic.assert_not_called()


class ClaudePricingTests(SimpleTestCase):
    def test_claude_calls_have_a_cost(self):
        import datetime

        from .pricing import cost
        now = datetime.datetime(2026, 11, 18, 10, 0, tzinfo=datetime.timezone.utc)
        # Measured 2026-11-18: a 9-post plan on Sonnet used 5,944 input and 5,387 output tokens and cost about $0.066.
        self.assertAlmostEqual(cost('claude-sonnet-5-5', 5944, 0, 5387, now), 0.0657, places=3)
        self.assertAlmostEqual(cost('claude-opus-5-5-20261001', 5944, 0, 9362, now), 0.2110, places=3)
        self.assertAlmostEqual(cost('claude-sonnet-5-5', 10000, 8000, 1000, now), (2000 * 2.0 + 8000 * 0.1 + 1000 * 10.0) / 1e6)
