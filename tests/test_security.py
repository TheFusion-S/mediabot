import json
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from bot.security import InitDataError, sign, validate_init_data
from tests.conftest import TOKEN, make_init_data


def test_valid_init_data():
    user = validate_init_data(make_init_data(), TOKEN)
    assert user.id == 42 and user.first_name == "Ali" and user.username == "ali"
    assert user.to_api() == {"id": 42, "first_name": "Ali", "username": "ali"}


def test_unicode_user_and_extra_fields():
    data = make_init_data({"id": 7, "first_name": "Oʻtkir", "last_name": "Ш"}, extra={"chat_type": "private",
                                                                                      "signature": "abc"})
    user = validate_init_data(data, TOKEN)
    assert user.id == 7 and user.username is None and user.first_name == "Oʻtkir"


def test_wrong_token():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(token="999:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"), TOKEN)


@pytest.mark.parametrize("field,value", [
    ("user", json.dumps({"id": 1, "first_name": "Admin"})),
    ("auth_date", str(int(time.time()) + 1)),
    ("query_id", "other"),
])
def test_tampered(field, value):
    pairs = dict(parse_qsl(make_init_data()))
    pairs[field] = value
    with pytest.raises(InitDataError):
        validate_init_data(urlencode(pairs), TOKEN)


def test_added_field_breaks_signature():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data() + "&is_admin=1", TOKEN)


def test_tampered_hash():
    data = make_init_data()
    pairs = dict(parse_qsl(data))
    pairs["hash"] = ("0" if pairs["hash"][0] != "0" else "1") + pairs["hash"][1:]
    with pytest.raises(InitDataError):
        validate_init_data(urlencode(pairs), TOKEN)


def test_expired():
    old = int(time.time()) - 24 * 3600 - 10
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(make_init_data(auth_date=old), TOKEN)


def test_almost_expired_ok():
    recent = int(time.time()) - 24 * 3600 + 60
    assert validate_init_data(make_init_data(auth_date=recent), TOKEN).id == 42


def test_future_auth_date_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(auth_date=int(time.time()) + 3600), TOKEN)


@pytest.mark.parametrize("raw", ["", "garbage", "hash=", "a=1&a=2&hash=x", "x" * 10000, "user=%7B%7D"])
def test_malformed(raw):
    with pytest.raises(InitDataError):
        validate_init_data(raw, TOKEN)


def test_duplicate_keys_rejected_even_if_signed():
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 5, "first_name": "x"})}
    h = sign(fields, TOKEN)
    raw = urlencode(fields) + "&user=" + json.dumps({"id": 6}) + "&hash=" + h
    with pytest.raises(InitDataError):
        validate_init_data(raw, TOKEN)


def test_missing_user():
    fields = {"auth_date": str(int(time.time()))}
    fields["hash"] = sign(fields, TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(urlencode(fields), TOKEN)


def test_uses_compare_digest(monkeypatch):
    import hmac as _hmac

    import bot.security as sec

    calls = []
    real = _hmac.compare_digest
    monkeypatch.setattr(sec.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    validate_init_data(make_init_data(), TOKEN)
    assert calls
