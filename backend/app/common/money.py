"""Decimal helpers for money/quantity values.

Every persisted money or quantity column in this app is `Numeric(p, s)` at the DB
level (see `ARCHITECTURE.md`'s "Decimal money and unit-safe quantities" section), and
SQLAlchemy already hands back a real `decimal.Decimal` for those columns, on Postgres
*and* SQLite -- it always has. The bug this module exists to close was never at the
DB boundary; it was that the Python-side code between the DB and the API response
treated those `Decimal`s as `float` (explicit `float(...)` casts scattered through
`valuation`/`risk`/`limits`), so every sum/average/comparison over more than a
handful of trades accumulated ordinary IEEE-754 binary-float rounding error -- the
exact failure mode Decimal exists to prevent for money.

The one place `float` is still correct and unavoidable is *quant math*: Black-76,
historical-simulation VaR, bump-and-revalue sensitivities -- numpy/scipy have no
Decimal support and no real benefit from it (these are already approximate numerical
methods, not exact bookkeeping). `to_decimal` is the one clean conversion point for
handing a quant module's float *output* back across that boundary into the
exact-arithmetic world once, rather than never converting at all (leaving persisted
P&L/VaR/sensitivity values silently `float`) or converting via `Decimal(a_float)`
directly (which captures the float's exact binary value, e.g.
`Decimal(3.1) == Decimal('3.10000000000000008881784197001...')` -- noise nobody
wants to see in a persisted, audited money value).
"""

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

# A Pydantic field type for money/quantity API schema fields: `Decimal` on the Python
# side (exact validation -- see to_decimal's note on how Pydantic safely parses a
# JSON number into Decimal without introducing binary-float noise), but serialized to
# JSON as a plain number, not Pydantic v2's own default (a JSON *string*, e.g.
# `"123.456000"` -- exact, but a wire-format change that would ripple through every
# frontend consumer and the generated OpenAPI types for zero real benefit here). The
# bug this whole module exists to fix was repeated arithmetic over many trades
# silently losing precision, not a single, final, correctly-rounded JSON-number
# render of an already-exact value -- so keeping the wire format as `number` costs
# nothing and avoids an unrelated, sprawling frontend contract change.
MoneyDecimal = Annotated[
    Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
]


def to_decimal(value: int | float | str | Decimal) -> Decimal:
    """Converts a `float` quant-computation output (or an `int`/`str` value, e.g. from
    a loosely-typed JSON payload like an amendment's `changes` dict) to `Decimal` via
    its shortest round-tripping decimal string representation (`str(float)`, not
    `Decimal(float)`) -- `str(3.1)` is `"3.1"`, so `Decimal(str(3.1))` is exactly
    `Decimal('3.1')`, not the binary float's true value out to 50-odd digits. A no-op
    if `value` is already a `Decimal` (the common case once a value has entered the
    exact-arithmetic side of the boundary -- callers don't need to know or care which
    they were handed)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def format_decimal(value: Decimal) -> str:
    """Human-readable rendering for an error/log message: trailing zeros stripped
    (`Decimal('1000.000000')` -> `"1000"`, not `"1000.000000"`), without the
    scientific notation `Decimal.normalize()` produces on its own for round values
    (`Decimal('1000.000000').normalize()` is `Decimal('1E+3')`, not what anyone wants
    to read in a limit-breach message) -- forcing fixed-point formatting after
    normalizing avoids that. This is for *display* only; never use it to feed a value
    back into arithmetic or persistence, where the exact (un-normalized) Decimal is
    what belongs."""
    return format(value.normalize(), "f")
