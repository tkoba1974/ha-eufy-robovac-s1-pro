import math
from hashlib import md5

from cryptography.hazmat.backends.openssl import backend as openssl_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .constants import TUYA_PASSWORD_IV, TUYA_PASSWORD_KEY


def unpadded_rsa(key_exponent: int, key_n: int, plaintext: bytes) -> bytes:
    # RSA with no padding, as per https://github.com/pyca/cryptography/issues/2735#issuecomment-276356841
    keylength = math.ceil(key_n.bit_length() / 8)
    input_nr = int.from_bytes(plaintext, byteorder="big")
    crypted_nr = pow(input_nr, key_exponent, key_n)
    return crypted_nr.to_bytes(keylength, byteorder="big")


def shuffled_md5(value: str) -> str:
    # shuffling the hash reminds me of https://security.stackexchange.com/a/25588
    # from https://github.com/TuyaAPI/cloud/blob/9b108f4d347c81c3fd6d73f3a2bb08a646a2f6e1/index.js#L99
    _hash = md5(value.encode("utf-8")).hexdigest()
    return _hash[8:16] + _hash[0:8] + _hash[24:32] + _hash[16:24]


TUYA_PASSWORD_INNER_CIPHER = Cipher(
    algorithms.AES(TUYA_PASSWORD_KEY),
    modes.CBC(TUYA_PASSWORD_IV),
    backend=openssl_backend,
)
