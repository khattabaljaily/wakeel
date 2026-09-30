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


@override_settings(AI_PROVIDER='deepseek', AI_ENABLED=True, DEEPSEEK_API_KEY='k', DEEPSEEK_MODEL='deepseek-v4-pro',
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
        with self.assertRaisesMessage(AIError, 'رصيد'):
            call_json('s', 'p', SCHEMA)
        post.return_value = reply('{"a": "x', finish='length')
        with self.assertRaisesMessage(AIError, 'أطول'):
            call_json('s', 'p', SCHEMA)
        post.return_value = reply('{"b": 1}')
        with self.assertRaisesMessage(AIError, 'ناقص'):
            call_json('s', 'p', SCHEMA)
