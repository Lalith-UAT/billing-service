import ast
from decimal import Decimal

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.USub,
    ast.UAdd,
)


def _eval_rule(rule, total):
    if not isinstance(rule, str):
        raise ValueError("discount rule must be a string")
    tree = ast.parse(rule, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("unsupported discount rule")
        if isinstance(node, ast.Name) and node.id != "total":
            raise ValueError("unsupported discount rule")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("unsupported discount rule")
    return eval(compile(tree, "<discount>", "eval"), {"__builtins__": {}}, {"total": total})


def apply_discount(total, rule):
    return Decimal(str(_eval_rule(rule, float(total)))).quantize(Decimal("0.01"))
