import pytest

from app.tools.calculator import CalculationError, safe_calculate


def test_basic_arithmetic() -> None:
    assert safe_calculate("2 + 3") == 5
    assert safe_calculate("10 - 4") == 6
    assert safe_calculate("6 * 7") == 42
    assert safe_calculate("10 / 4") == 2.5
    assert safe_calculate("2 ** 8") == 256
    assert safe_calculate("10 % 3") == 1


def test_operator_precedence_and_parentheses() -> None:
    assert safe_calculate("2 + 3 * 4") == 14
    assert safe_calculate("(2 + 3) * 4") == 20


def test_unary_operators() -> None:
    assert safe_calculate("-5 + 3") == -2
    assert safe_calculate("+5") == 5


def test_float_expression() -> None:
    assert safe_calculate("4.5 * 2.72") == pytest.approx(12.24)


def test_division_by_zero_raises() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("1 / 0")


def test_huge_exponent_rejected() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("2 ** 100000")


def test_invalid_syntax_raises() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("2 +")


def test_expression_too_long_rejected() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("1+" * 200)


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "[x for x in range(10)]",
        "(lambda: 1)()",
        "1 if True else 0",
        "os.system('ls')",
        "eval('1+1')",
        "().__class__",
    ],
)
def test_non_arithmetic_input_is_rejected(malicious: str) -> None:
    with pytest.raises(CalculationError):
        safe_calculate(malicious)


def test_string_literal_rejected() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("'hello'")


def test_boolean_literal_rejected() -> None:
    with pytest.raises(CalculationError):
        safe_calculate("True")
