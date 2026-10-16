"""
The arithmetic of active tables, as app/static/js/sheet.js does it in the page.

An export prints a table's numbers from the server, so they must come out as
the page shows them: the same formulas, the same waiting for cells still to be
filled in, and the same way of writing a number. See sheet.js for the rules;
tests/test_sheet.py holds the two to the same examples.
"""

import math
import re
from typing import Any, Callable, Dict, List, Optional


class _Pending:
    def __repr__(self):
        return 'PENDING'


PENDING = _Pending()


class SheetError(Exception):
    pass


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_name(index: int) -> str:
    s, n = '', index + 1
    while n > 0:
        s = chr(65 + (n - 1) % 26) + s
        n = (n - 1) // 26
    return s


_TOKEN = re.compile(r'(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z]+)(\d+)?(?::([A-Za-z]+)(\d+))?'
                    r'|(<=|>=|<>|[-+*/^(),;<>=])')


def _tokenize(src: str) -> List[dict]:
    tokens, pos = [], 0
    while pos < len(src):
        if src[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(src, pos)
        if not m:
            raise SheetError(f'cannot read "{src[pos:].strip()}"')
        pos = m.end()
        if m.group(1) is not None:
            tokens.append({'t': 'num', 'v': float(m.group(1))})
        elif m.group(2) is not None:
            if m.group(4) is not None:
                tokens.append({'t': 'range', 'c1': col_index(m.group(2)), 'r1': int(m.group(3) or 0) - 1,
                               'c2': col_index(m.group(4)), 'r2': int(m.group(5)) - 1})
            elif m.group(3) is not None:
                tokens.append({'t': 'ref', 'c': col_index(m.group(2)), 'r': int(m.group(3)) - 1})
            else:
                tokens.append({'t': 'name', 'v': m.group(2).upper()})
        else:
            tokens.append({'t': 'op', 'v': ',' if m.group(6) == ';' else m.group(6)})
    return tokens


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _truthy(v: Any) -> bool:
    """JavaScript's idea of true: not 0, not '', not empty."""
    if v is None or v is PENDING:
        return v is PENDING
    if isinstance(v, (int, float)):
        return v != 0 and not math.isnan(v)
    if isinstance(v, str):
        return v != ''
    return True


def _arith(a, b, f):
    if a is PENDING or b is PENDING or a is None or b is None:
        return PENDING
    if not _is_num(a) or not _is_num(b):
        raise SheetError('not a number')
    return f(a, b)


def _pow(a: float, b: float) -> float:
    """a ** b as JavaScript has it: Infinity rather than an error, NaN rather than a complex number."""
    try:
        v = float(a) ** b
    except (ZeroDivisionError, OverflowError):
        return math.inf
    return math.nan if isinstance(v, complex) else v


def _flat(args):
    out = []
    for a in args:
        out.extend(a if isinstance(a, list) else [a])
    return out


def _numbers(args):
    xs = []
    for v in _flat(args):
        if v is PENDING:
            return None
        if _is_num(v):
            xs.append(v)
    return xs


def _sum(args):
    xs = _numbers(args)
    return PENDING if xs is None else float(sum(xs))


def _extreme(pick):
    def run(args):
        xs = _numbers(args)
        return PENDING if not xs else pick(xs)
    return run


def _average(args):
    xs = _numbers(args)
    return PENDING if not xs else sum(xs) / len(xs)


def _js_round(x: float) -> float:
    """Math.round: halves go up."""
    return float(math.floor(x + 0.5))


def _round(args):
    x = args[0] if args else None
    d = args[1] if len(args) > 1 else None
    if x is PENDING or x is None:
        return PENDING
    if not _is_num(x):
        return math.nan
    k = 10 ** (d if _is_num(d) else 0)
    return _js_round(x * k) / k


def _abs(args):
    x = args[0] if args else None
    if x is PENDING or x is None:
        return PENDING
    return abs(x) if _is_num(x) else math.nan


def _if(args):
    c = args[0] if args else None
    a = args[1] if len(args) > 1 else None
    b = args[2] if len(args) > 2 else None
    if c is PENDING:
        return PENDING
    return a if _truthy(c) else ('' if b is None else b)


FUNCTIONS: Dict[str, Callable] = {'SUM': _sum, 'MIN': _extreme(min), 'MAX': _extreme(max), 'AVERAGE': _average,
                                  'AVG': _average, 'ROUND': _round, 'ABS': _abs, 'IF': _if}


def evaluate(src: str, get: Callable[[int, int], Any], row: Optional[int] = None, scale: float = 1.0):
    tokens = _tokenize(src)
    i = 0

    def peek():
        return tokens[i] if i < len(tokens) else None

    def take(v):
        nonlocal i
        if i < len(tokens) and tokens[i]['t'] == 'op' and tokens[i]['v'] == v:
            i += 1
            return True
        return False

    def primary():
        nonlocal i
        if i >= len(tokens):
            raise SheetError('formula ends too soon')
        tok = tokens[i]
        i += 1
        if tok['t'] == 'num':
            return tok['v']
        if tok['t'] == 'ref':
            return get(tok['r'], tok['c'])
        if tok['t'] == 'range':
            out = []
            for r in range(min(tok['r1'], tok['r2']), max(tok['r1'], tok['r2']) + 1):
                for c in range(min(tok['c1'], tok['c2']), max(tok['c1'], tok['c2']) + 1):
                    out.append(get(r, c))
            return out
        if tok['t'] == 'name':
            if take('('):
                fn = FUNCTIONS.get(tok['v'])
                if fn is None:
                    raise SheetError(f"no function {tok['v']}")
                args = []
                if not take(')'):
                    while True:
                        args.append(comparison())
                        if not take(','):
                            break
                    if not take(')'):
                        raise SheetError('missing )')
                return fn(args)
            if tok['v'] == 'N':
                return scale
            if row is None:
                raise SheetError(f"{tok['v']} needs a row number")
            return get(row, col_index(tok['v']))
        if tok['t'] == 'op' and tok['v'] == '(':
            v = comparison()
            if not take(')'):
                raise SheetError('missing )')
            return v
        if tok['t'] == 'op' and tok['v'] == '-':
            return _arith(0.0, power(), lambda a, b: a - b)
        if tok['t'] == 'op' and tok['v'] == '+':
            return power()
        raise SheetError(f"unexpected {tok.get('v', 'text')}")

    def power():
        nonlocal i
        v = primary()
        while peek() and peek().get('v') == '^':
            i += 1
            r = primary()
            v = _arith(v, r, _pow)
        return v

    def term():
        nonlocal i
        v = power()
        while peek() and peek().get('v') in ('*', '/'):
            op = tokens[i]['v']
            i += 1
            r = power()

            def f(a, b, op=op):
                if op == '/' and b == 0:
                    raise SheetError('#DIV/0')
                return a * b if op == '*' else a / b
            v = _arith(v, r, f)
        return v

    def total():
        nonlocal i
        v = term()
        while peek() and peek().get('v') in ('+', '-'):
            op = tokens[i]['v']
            i += 1
            r = term()
            v = _arith(v, r, lambda a, b, op=op: a + b if op == '+' else a - b)
        return v

    def comparison():
        nonlocal i
        v = total()
        while peek() and peek().get('v') in ('<', '>', '<=', '>=', '=', '<>'):
            op = tokens[i]['v']
            i += 1
            r = total()
            tests = {'<': lambda a, b: a < b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b,
                     '>=': lambda a, b: a >= b, '=': lambda a, b: a == b, '<>': lambda a, b: a != b}
            v = _arith(v, r, lambda a, b, op=op: 1.0 if tests[op](a, b) else 0.0)
        return v

    value = comparison()
    if i < len(tokens):
        raise SheetError(f"unexpected {tokens[i].get('v', 'text')}")
    return value


_NUMBERLIKE = re.compile(r'^[-+]?(\d|\.\d)')


def _literal(raw: Any):
    s = str('' if raw is None else raw).strip()
    if s == '':
        return None
    candidate = s.replace(',', '.', 1)
    if _NUMBERLIKE.match(s) and '_' not in candidate:
        try:
            n = float(candidate)
            if math.isfinite(n):
                return n
        except ValueError:
            pass
    return s


def compute(table: dict) -> List[List[dict]]:
    """Every cell of a table: {value, display, error?, formula?}, as the page works it out."""
    columns = table.get('columns') or []
    rows = table.get('rows') or []
    sc = table.get('scale')
    scale = _number(sc.get('value'), 0.0) if sc else 1.0
    base = (_number(sc.get('base'), 1.0) or 1.0) if sc else 1.0
    factor = scale / base
    memo: Dict[tuple, dict] = {}
    busy = set()
    numeric = {'number', 'scaled', 'fill'}

    def cells(r):
        return (rows[r] or {}).get('cells') or []

    def raw_at(r, c):
        cs = cells(r)
        return cs[c] if c < len(cs) else None

    row_used = [any((col or {}).get('kind') != 'check' and str('' if raw_at(r, c) is None else raw_at(r, c)).strip() != ''
                    for c, col in enumerate(columns)) for r in range(len(rows))]

    def cell_formula(r, c):
        col = columns[c] or {}
        raw = raw_at(r, c)
        if isinstance(raw, str) and raw.strip().startswith('='):
            return raw.strip()[1:]
        if raw in ('', None) and col.get('kind') == 'formula' and col.get('formula'):
            return re.sub(r'^=', '', str(col['formula']).strip())
        return None

    def get(r, c):
        if r < 0 or c < 0 or r >= len(rows) or c >= len(columns):
            raise SheetError('#REF')
        key = (r, c)
        if key in memo:
            m = memo[key]
            if m.get('error'):
                raise SheetError(m['error'])
            return m['value']
        if key in busy:
            raise SheetError('#CYCLE')
        busy.add(key)
        try:
            col = columns[c] or {}
            raw = raw_at(r, c)
            formula = cell_formula(r, c)
            if col.get('kind') == 'check':
                result = {'value': 1.0 if raw else 0.0}
            elif formula is not None:
                v = evaluate(formula, get, row=r, scale=scale)
                if isinstance(v, list):
                    raise SheetError('a range needs a function, e.g. SUM')
                if col.get('kind') == 'scaled' and _is_num(v):
                    v *= factor
                result = {'value': v, 'formula': True}
            else:
                v = _literal(raw)
                if col.get('kind') == 'scaled' and _is_num(v):
                    v *= factor
                if v is None and col.get('kind') in numeric and row_used[r]:
                    v = PENDING
                result = {'value': v}
        except SheetError as err:
            result = {'value': None, 'error': str(err)}
        except (OverflowError, ZeroDivisionError, TypeError, ValueError) as err:
            result = {'value': None, 'error': str(err)}
        busy.discard(key)
        memo[key] = result
        if result.get('error'):
            raise SheetError(result['error'])
        return result['value']

    out = []
    for r in range(len(rows)):
        line = []
        for c in range(len(columns)):
            try:
                get(r, c)
            except SheetError:
                pass
            m = memo.get((r, c), {'value': None})
            display = '#' + m['error'].lstrip('#') if m.get('error') else show(m['value'])
            line.append({**m, 'display': display})
        out.append(line)
    return out


def _number(value: Any, default: float) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def js_number(value: float) -> str:
    """A number written as JavaScript's String(number) writes it."""
    if value == 0:
        return '0'
    if not math.isfinite(value):
        return 'NaN' if math.isnan(value) else ('Infinity' if value > 0 else '-Infinity')
    sign = '-' if value < 0 else ''
    digits, exp = _shortest(abs(value))     # value = 0.digits × 10^exp
    k = len(digits)
    if k <= exp <= 21:
        body = digits + '0' * (exp - k)
    elif 0 < exp <= 21:
        body = digits[:exp] + '.' + digits[exp:]
    elif -6 < exp <= 0:
        body = '0.' + '0' * (-exp) + digits
    else:
        e = exp - 1
        body = digits[0] + ('.' + digits[1:] if k > 1 else '') + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    return sign + body


def _shortest(x: float):
    """The shortest digits that read back as x, and where the decimal point goes."""
    mantissa, _, exponent = f'{x!r}'.partition('e') if 'e' in repr(x) else (repr(x), '', '0')
    whole, _, frac = mantissa.partition('.')
    digits = (whole + frac).lstrip('0')
    lead = len(whole) - (len(whole + frac) - len((whole + frac).lstrip('0')))
    exp = int(exponent) + lead
    digits = digits.rstrip('0') or '0'
    return digits, exp


def show(value: Any) -> str:
    """A number as people write it, as sheet.js shows it."""
    if value is None or value is PENDING:
        return ''
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)
    if not math.isfinite(value):
        return '#NUM'
    a = abs(value)
    if a != 0 and a < 0.1:
        return js_number(float(f'{value:.2g}'))
    return js_number(math.floor(value * 100 + 0.5) / 100)
