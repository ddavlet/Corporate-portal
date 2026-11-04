"""Локальный калькулятор для агента: точная десятичная арифметика без eval.

Модель не должна считать деньги «в уме»: любое сложение, процент или конвертация
идёт через инструмент `calculate`. Выражение разбирается через ast и вычисляется
только по белому списку узлов; числа берутся из исходного текста (не через float),
поэтому 0.1 + 0.2 == 0.3 точно.
"""

from __future__ import annotations

import ast
import decimal
from decimal import Decimal

CALCULATOR_TOOL_NAME = "calculate"

CALCULATOR_TOOL = {
    "name": CALCULATOR_TOOL_NAME,
    "description": (
        "Exact decimal arithmetic for money. Supports + - * / , parentheses, unary minus and decimal "
        "numbers written with a dot. Do not use thousands separators (write 1250000, not 1 250 000). "
        "Use it for every sum, difference, percentage (write x * 15 / 100) and currency conversion "
        "instead of calculating in your head. Returns the exact result as a plain decimal number."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression, for example: (1250000.50 + 3400000) * 15 / 100",
            }
        },
        "required": ["expression"],
    },
}

MAX_EXPRESSION_LENGTH = 2000
MAX_DEPTH = 50
_PRECISION = 34
_MAX_ABS_EXPONENT = 1000


class CalculatorError(ValueError):
    """Выражение неверно или не поддерживается; текст безопасно отдать модели."""


def _context() -> decimal.Context:
    return decimal.Context(
        prec=_PRECISION,
        Emax=_MAX_ABS_EXPONENT,
        Emin=-_MAX_ABS_EXPONENT,
        traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow],
    )


def _unsupported(node: ast.AST) -> CalculatorError:
    return CalculatorError(f"Unsupported expression: {type(node).__name__}")


def _number(node: ast.Constant, source: str) -> Decimal:
    value = node.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculatorError(f"Unsupported expression: constant {type(value).__name__}")
    segment = (ast.get_source_segment(source, node) or "").strip()
    if not segment or "_" in segment:
        raise CalculatorError("Unsupported expression: number format")
    try:
        return Decimal(segment)
    except decimal.InvalidOperation:
        raise CalculatorError(f"Unsupported expression: number {segment!r}") from None


def _eval(node: ast.AST, source: str, ctx: decimal.Context, depth: int) -> Decimal:
    if depth > MAX_DEPTH:
        raise CalculatorError("Expression is nested too deeply")
    if isinstance(node, ast.Constant):
        return _number(node, source)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _eval(node.operand, source, ctx, depth + 1)
        return ctx.minus(operand) if isinstance(node.op, ast.USub) else ctx.plus(operand)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval(node.left, source, ctx, depth + 1)
        right = _eval(node.right, source, ctx, depth + 1)
        if isinstance(node.op, ast.Add):
            return ctx.add(left, right)
        if isinstance(node.op, ast.Sub):
            return ctx.subtract(left, right)
        if isinstance(node.op, ast.Mult):
            return ctx.multiply(left, right)
        if right == 0:
            raise CalculatorError("Division by zero")
        return ctx.divide(left, right)
    raise _unsupported(node)


def _format(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def evaluate(expression: str) -> str:
    """Вычислить выражение; результат — десятичная строка без экспоненты и лишних нулей."""
    if not isinstance(expression, str):
        raise CalculatorError("Expression must be a string")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(f"Expression is too long (max {MAX_EXPRESSION_LENGTH} characters)")
    source = expression.strip()
    if not source:
        raise CalculatorError("Expression is empty")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise CalculatorError(f"Invalid expression: {exc.__class__.__name__}") from None
    ctx = _context()
    try:
        result = _eval(tree.body, source, ctx, 1)
        return _format(ctx.plus(result))
    except CalculatorError:
        raise
    except decimal.DecimalException as exc:
        raise CalculatorError(f"Calculation failed: {exc.__class__.__name__}") from None
    except RecursionError:
        raise CalculatorError("Expression is nested too deeply") from None
