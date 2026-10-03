import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

key = ec.generate_private_key(ec.SECP256R1())
priv = b64(key.private_numbers().private_value.to_bytes(32, "big"))
pub = b64(key.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
print("VAPID_PUBLIC_KEY=" + pub)
print("VAPID_PRIVATE_KEY=" + priv)