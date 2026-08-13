"""Pure domain logic, no database (spec §5)."""

from domain.users.passwords import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_is_argon2id() -> None:
    # argon2-cffi's default PasswordHasher profile is argon2id (spec §78);
    # the encoded hash string names its own algorithm, so this is checkable
    # without depending on the library's internal defaults staying the same.
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")


def test_same_password_hashes_differently_each_time() -> None:
    # A fresh random salt per hash — two hashes of the same password must
    # never be equal, or the salt isn't doing its job.
    a = hash_password("correct horse battery staple")
    b = hash_password("correct horse battery staple")
    assert a != b
