from decimal import Decimal

from django.test import SimpleTestCase

from apps.modules.ai_assistant.pricing import cost_usd


class CostUsdTests(SimpleTestCase):
    def test_sonnet_cost(self):
        cost = cost_usd(
            "claude-sonnet-5-5",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        self.assertEqual(cost, Decimal("12.00"))

    def test_cache_tokens_priced(self):
        cost = cost_usd(
            "claude-sonnet-5-5",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
        )
        # 0.20 (чтение кеша) + 2.50 (запись кеша, 5 минут)
        self.assertEqual(cost, Decimal("2.70"))

    def test_unknown_model_zero(self):
        with self.assertLogs("apps.modules.ai_assistant.pricing", level="WARNING"):
            cost = cost_usd(
                "unknown-model",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_tokens=0,
                cache_creation_tokens=0,
            )
        self.assertEqual(cost, Decimal("0"))
