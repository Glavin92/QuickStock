# chat_crypto.py — AES-256-GCM encryption utilities for QuickStock Chat
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_master_key() -> bytes:
    """Lazy-load master key from env so module can be imported before .env is loaded."""
    raw = os.getenv("CHAT_MASTER_KEY", "")
    if not raw:
        raise RuntimeError(
            "CHAT_MASTER_KEY env var is missing. "
            "Generate with: python -c \"import os,base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("CHAT_MASTER_KEY must be a 32-byte base64 string.")
    return key


def generate_conversation_key() -> bytes:
    """Generate a new random 256-bit AES key for a conversation."""
    return os.urandom(32)


def encrypt_key(raw_key: bytes) -> dict:
    """Encrypt a conversation key using the server MASTER_KEY."""
    master = _get_master_key()
    iv = os.urandom(12)
    aesgcm = AESGCM(master)
    ciphertext_with_tag = aesgcm.encrypt(iv, raw_key, None)
    # GCM appends 16-byte auth tag at the end
    ciphertext = ciphertext_with_tag[:-16]
    auth_tag   = ciphertext_with_tag[-16:]
    return {
        "encrypted_key": base64.b64encode(ciphertext).decode(),
        "key_iv":        base64.b64encode(iv).decode(),
        "key_auth_tag":  base64.b64encode(auth_tag).decode(),
    }


def decrypt_key(encrypted_key: str, key_iv: str, key_auth_tag: str) -> bytes:
    """Decrypt a conversation key using the server MASTER_KEY."""
    master     = _get_master_key()
    iv         = base64.b64decode(key_iv)
    ciphertext = base64.b64decode(encrypted_key)
    auth_tag   = base64.b64decode(key_auth_tag)
    aesgcm     = AESGCM(master)
    raw_key    = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
    return raw_key


def encrypt_message(raw_text: str, conversation_key: bytes) -> dict:
    """Encrypt a message string with the given AES-256-GCM key."""
    iv = os.urandom(12)
    aesgcm = AESGCM(conversation_key)
    ciphertext_with_tag = aesgcm.encrypt(iv, raw_text.encode("utf-8"), None)
    ciphertext = ciphertext_with_tag[:-16]
    auth_tag   = ciphertext_with_tag[-16:]
    return {
        "encrypted_body": base64.b64encode(ciphertext).decode(),
        "iv":             base64.b64encode(iv).decode(),
        "auth_tag":       base64.b64encode(auth_tag).decode(),
    }


def decrypt_message(encrypted_body: str, iv: str, auth_tag: str,
                    conversation_key: bytes) -> str:
    """Decrypt a stored message ciphertext."""
    iv_bytes   = base64.b64decode(iv)
    ciphertext = base64.b64decode(encrypted_body)
    tag_bytes  = base64.b64decode(auth_tag)
    aesgcm     = AESGCM(conversation_key)
    plaintext  = aesgcm.decrypt(iv_bytes, ciphertext + tag_bytes, None)
    return plaintext.decode("utf-8")
