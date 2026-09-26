from muse.tools.approval_key import compute_approval_key

BASE = {
    "tool": "gmail.send",
    "args": {"to": "a@example.com", "body": "hi"},
    "destination": "a@example.com",
    "credential_ref": "gmail:owner",
    "user_id": "u1",
}


def key(**overrides: object) -> str:
    return compute_approval_key(**{**BASE, **overrides})  # type: ignore[arg-type]


def test_key_is_stable_across_arg_order():
    assert key(args={"body": "hi", "to": "a@example.com"}) == key()


def test_any_identity_field_changes_the_key():
    base = key()
    assert key(args={"to": "b@example.com", "body": "hi"}) != base
    assert key(destination="b@example.com") != base
    assert key(credential_ref="gmail:other") != base
    assert key(user_id="u2") != base
    assert key(tool="gmail.draft") != base


def test_key_is_sha256_hex():
    assert len(key()) == 64
    int(key(), 16)
