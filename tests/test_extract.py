from datetime import date, datetime, timedelta, timezone

import pytest

from cerberus.extract import extract_all
from cerberus.textnorm import clean

CREATED = datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=3)))  # a Tuesday


def ex(text):
    return extract_all(clean(text), CREATED)


@pytest.mark.parametrize("text, value, currency", [
    ("حولت مليون ونص لاخوي", 1_500_000, "IQD"),
    ("دزيت ٢٥٠ الف لصديقي", 250_000, "IQD"),
    ("حولت نص مليون لرقم غلط", 500_000, "IQD"),
    ("الحوالة مال ٣ مليون ما وصلت", 3_000_000, "IQD"),
    ("I sent 200$ to the wrong number", 200, "USD"),
    ("7awalt 100 alf", 100_000, "IQD"),
    ("شحنت رصيد ب ١٠ الاف", 10_000, "IQD"),
    ("بمبلغ 500000 دينار", 500_000, "IQD"),
    ("بالحساب مليونين", 2_000_000, "IQD"),
    ("سحبت خمسين الف", 50_000, "IQD"),
])
def test_amounts(text, value, currency):
    first = ex(text).first("amounts")
    assert first is not None and first.value == value and first.currency == currency


@pytest.mark.parametrize("text", ["شلون افتح حساب لابني عمره ١٥ سنة؟", "جربت خمس مرات", "رقم العملية 8823419"])
def test_no_false_amounts(text):
    assert ex(text).amounts == []


def test_refs_and_phones_do_not_become_amounts():
    e = ex("حولت ٥ مليون للرقم 07801234567 ورقم العملية 6610238")
    assert [f.value for f in e.amounts] == [5_000_000]
    assert e.first("phones").value == "07801234567"
    assert e.first("refs").value == "6610238"


@pytest.mark.parametrize("text, ref", [
    ("رقم الحوالة TXN-55120934", "TXN-55120934"),
    ("ورقمها 99120455", "99120455"),
    ("transaction 5523001 please", "5523001"),
    ("رقم الوصل 300219877", "300219877"),
])
def test_refs(text, ref):
    assert ex(text).first("refs").value == ref


@pytest.mark.parametrize("text, expected", [
    ("حولت امس بالليل", date(2026, 10, 19)),
    ("من البارحة", date(2026, 10, 19)),
    ("يوم الجمعة", date(2026, 10, 16)),
    ("من ثلاث ايام", date(2026, 10, 17)),
    ("sar 3 ayam", date(2026, 10, 17)),
    ("صارلي اسبوع", date(2026, 10, 13)),
    ("قبل ساعتين", date(2026, 10, 20)),
    ("بتاريخ 15/10", date(2026, 10, 15)),
])
def test_dates(text, expected):
    assert ex(text).first("dates").value == expected


def test_quotes_are_exact_substrings():
    text = "الوكيل بالمنصور گال النظام عاطل وما رجعلي ٢٠٠ الف"
    e = ex(text)
    assert e.first("agents").value == "المنصور"
    for found in e.amounts + e.agents:
        assert found.quote in clean(text)
