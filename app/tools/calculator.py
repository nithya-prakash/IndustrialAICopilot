"""Safe arithmetic evaluator for the `calculate` tool. Deliberately not
`eval()` — a tool the LLM calls with model-chosen input is exactly the
kind of thing that must not be able to execute arbitrary Python. This
parses the expression to an AST and only walks a whitelist of arithmetic
node types (numbers, +-*/ %, **, unary +-, parentheses); anything else
(names, calls, attribute access, comprehensions, ...) is rejected before
evaluation ever happens.
"""
import ast
import operator

_ALLOWED_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_MAX_EXPONENT = 1000  # guards against a**b blowing up on huge b


class CalculationError(Exception):
    pass


def safe_calculate(expression: str) -> float:
    if len(expression) > 200:
        raise CalculationError("Expression too long")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"Invalid expression: {exc}") from exc

    try:
        return _eval_node(tree.body)
    except (TypeError, ZeroDivisionError, OverflowError) as exc:
        raise CalculationError(str(exc)) from exc


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        raise CalculationError(f"Unsupported constant: {node.value!r}")

    if isinstance(node, ast.BinOp):
        op_fn = _ALLOWED_BINARY_OPS.get(type(node.op))
        if op_fn is None:
            raise CalculationError(f"Unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise CalculationError("Exponent too large")
        return op_fn(left, right)

    if isinstance(node, ast.UnaryOp):
        op_fn = _ALLOWED_UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise CalculationError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.operand))

    raise CalculationError(f"Unsupported expression element: {type(node).__name__}")
