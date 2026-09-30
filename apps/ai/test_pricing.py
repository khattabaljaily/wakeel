import datetime

from django.test import SimpleTestCase, override_settings

from .client import AIResult
from .pricing import cost, deepseek_tier, is_off_peak

UTC = datetime.timezone.utc
PEAK = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
OFF_PEAK = datetime.datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


@override_settings(DEEPSEEK_OFF_PEAK_UTC=['16:30', '00:30'], AI_PRICE_INPUT_PER_MTOK=0, AI_PRICE_OUTPUT_PER_MTOK=0)
class PricingTests(SimpleTestCase):
    def test_model_names_map_to_tiers(self):
        self.assertEqual(deepseek_tier('deepseek-v4-pro'), 'pro')
        self.assertEqual(deepseek_tier('DeepSeek-V4-Pro-0813'), 'pro')
        self.assertEqual(deepseek_tier('deepseek-v4.1-flash'), 'flash')
        self.assertIsNone(deepseek_tier('claude-opus-5'))

    def test_off_peak_window_crosses_midnight(self):
        self.assertTrue(is_off_peak(OFF_PEAK))
        self.assertTrue(is_off_peak(datetime.datetime(2026, 10, 1, 0, 15, tzinfo=UTC)))
        self.assertFalse(is_off_peak(datetime.datetime(2026, 10, 1, 0, 30, tzinfo=UTC)))
        self.assertFalse(is_off_peak(PEAK))
        # A local time is judged in UTC: 19:00 in Doha is 16:00 UTC, still peak.
        doha = datetime.timezone(datetime.timedelta(hours=3))
        self.assertFalse(is_off_peak(datetime.datetime(2026, 10, 1, 19, 0, tzinfo=doha)))

    def test_pro_cost_splits_cache_hits_and_doubles_at_peak(self):
        # 1M input of which 400k cache hits, 1M output.
        off = cost('deepseek-v4-pro', 1_000_000, 400_000, 1_000_000, OFF_PEAK)
        self.assertAlmostEqual(off, 0.4 * 0.022 + 0.6 * 0.66 + 1.98)
        self.assertAlmostEqual(cost('deepseek-v4-pro', 1_000_000, 400_000, 1_000_000, PEAK), off * 2)

    def test_flash_cost(self):
        self.assertAlmostEqual(cost('deepseek-v4.1-flash', 2_000_000, 0, 0, PEAK), 0.6)

    def test_unknown_model_has_no_cost_unless_flat_prices_set(self):
        self.assertIsNone(cost('claude-opus-5', 1_000_000, 0, 1_000_000, PEAK))
        with self.settings(AI_PRICE_INPUT_PER_MTOK=5, AI_PRICE_OUTPUT_PER_MTOK=25):
            self.assertAlmostEqual(cost('claude-opus-5', 1_000_000, 0, 1_000_000, PEAK), 30)
