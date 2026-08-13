"""Password hashing. Pure — no I/O, no framework, no database (spec §5:
domain/ is the layer held to that bar).

Argon2id, via argon2-cffi's default profile, per spec §78.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
