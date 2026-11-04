from django.test import SimpleTestCase

from apps.modules.ai_assistant.calculator import CalculatorError, evaluate


class CalculatorTests(SimpleTestCase):
    def test_exact_decimal_addition(self):
        self.assertEqual(evaluate("0.1 + 0.2"), "0.3")

    def test_precedence_and_parentheses(self):
        self.assertEqual(evaluate("2 + 3 * (4 - 1)"), "11")

    def test_unary_minus(self):
        self.assertEqual(evaluate("-5 + 2"), "-3")
        self.assertEqual(evaluate("-(2 + 3) * 2"), "-10")

    def test_large_money_sum(self):
        self.assertEqual(evaluate("1250000.50 + 3400000 + 99.5"), "4650100")

    def test_percentage(self):
        self.assertEqual(evaluate("1250000 * 15 / 100"), "187500")

    def test_division_by_zero_error(self):
        with self.assertRaisesMessage(CalculatorError, "Division by zero"):
            evaluate("1 / 0")

    def test_rejects_names_calls_attributes_and_power(self):
        for expression in ("__import__('os')", "a + 1", "(1).real", "2 ** 10", "7 % 3"):
            with self.subTest(expression=expression), self.assertRaises(CalculatorError):
                evaluate(expression)

    def test_too_long_expression_rejected(self):
        with self.assertRaises(CalculatorError):
            evaluate("1 + " * 600 + "1")

    def test_too_deep_expression_rejected(self):
        with self.assertRaises(CalculatorError):
            evaluate("-" * 80 + "1")

    def test_no_exponent_in_result(self):
        self.assertEqual(evaluate("0.0000001 * 1"), "0.0000001")
        self.assertEqual(evaluate("1e3 + 1"), "1001")

    def test_periodic_division_has_fixed_precision(self):
        self.assertEqual(evaluate("100 / 3"), "33.33333333333333333333333333333333")

    def test_long_sum_of_many_terms(self):
        self.assertEqual(evaluate("1" + "+1" * 999), "1000")
        self.assertEqual(evaluate("1000" + "-1" * 996), "4")

    def test_overflow_is_calculator_error(self):
        with self.assertRaises(CalculatorError):
            evaluate("1e999999999 * 1e999999999")
