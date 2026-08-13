"""domain/collection/material_change.py — pure, no I/O, no database."""

from domain.collection.material_change import ObservedValue, is_material_change

BASE = ObservedValue(price_minor=61200, currency="EUR")


def test_first_observation_is_always_material() -> None:
    assert is_material_change(None, BASE) is True


def test_identical_value_is_not_material() -> None:
    same = ObservedValue(price_minor=61200, currency="EUR")
    assert is_material_change(BASE, same) is False


def test_price_change_is_material() -> None:
    changed = ObservedValue(price_minor=61300, currency="EUR")
    assert is_material_change(BASE, changed) is True


def test_currency_change_is_material() -> None:
    changed = ObservedValue(price_minor=61200, currency="USD")
    assert is_material_change(BASE, changed) is True
