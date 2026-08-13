"""app.common.money: the Decimal boundary helpers task P1-7 introduced. See that
module's docstring for the design (float is fine for quant math; money/quantity
values that get summed/compared need Decimal all the way through)."""

from decimal import Decimal

from app.common.money import format_decimal, to_decimal


def test_to_decimal_is_a_no_op_for_an_already_decimal_value():
    value = Decimal("123.456")
    assert to_decimal(value) is value


def test_to_decimal_converts_a_float_via_its_shortest_round_tripping_string():
    # Decimal(3.1) directly would capture the binary float's true value out to ~50
    # digits (Decimal('3.100000000000000088817841970012523233890533447265625')) --
    # to_decimal must not do that.
    assert to_decimal(3.1) == Decimal("3.1")
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_converts_int_and_str():
    assert to_decimal(100) == Decimal("100")
    assert to_decimal("150.50") == Decimal("150.50")


def test_format_decimal_strips_trailing_zeros():
    assert format_decimal(Decimal("1000.000000")) == "1000"
    assert format_decimal(Decimal("123.456000")) == "123.456"


def test_format_decimal_never_uses_scientific_notation():
    # Decimal.normalize() alone turns a round number into scientific notation
    # (Decimal('1000.000000').normalize() == Decimal('1E+3')) -- format_decimal must
    # not leak that into a human-facing message.
    assert "E" not in format_decimal(Decimal("1000.000000"))
    assert "E" not in format_decimal(Decimal("0.000000"))
