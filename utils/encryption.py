import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging


class TokenEncryption:
    def __init__(self, encryption_key: str = None):
        """Initialize encryption with a key from environment or provided key"""
        if encryption_key is None:
            try:
                from config.settings import Settings
                settings = Settings()
                encryption_key = settings.token_encryption_key
                logging.debug(f"Loaded encryption key from settings: {encryption_key[:10]}..." if encryption_key else "No key found")
            except Exception as e:
                logging.error(f"Failed to load TOKEN_ENCRYPTION_KEY from settings: {e}")
                raise ValueError(f"TOKEN_ENCRYPTION_KEY environment variable is required. Error: {e}")
                
        if not encryption_key or encryption_key.strip() == "":
            raise ValueError("TOKEN_ENCRYPTION_KEY cannot be empty")
            
        # Check if we got a placeholder value instead of actual key
        if encryption_key.lower() in ['token_encryption_key', 'your_encryption_key_here', 'your_strong_encryption_key_here']:
            raise ValueError("TOKEN_ENCRYPTION_KEY appears to be a placeholder. Please set a real encryption key.")

        # Derive a key from the provided encryption key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'reminder_ai_salt',  # In production, use random salt per user
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
        self.cipher_suite = Fernet(key)

    def encrypt_token(self, token: str) -> str:
        """Encrypt a token and return base64 encoded encrypted data"""
        if not token:
            return None
        try:
            encrypted_token = self.cipher_suite.encrypt(token.encode())
            return base64.urlsafe_b64encode(encrypted_token).decode()
        except Exception as e:
            logging.error(f"Error encrypting token: {e}")
            raise

    def decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt a token from base64 encoded encrypted data"""
        if not encrypted_token:
            return None
        try:
            encrypted_data = base64.urlsafe_b64decode(encrypted_token.encode())
            decrypted_token = self.cipher_suite.decrypt(encrypted_data)
            return decrypted_token.decode()
        except Exception as e:
            logging.error(f"Error decrypting token: {e}")
            raise


# Global instance
_token_encryption = None


def get_token_encryption():
    """Get or create the global token encryption instance"""
    global _token_encryption
    if _token_encryption is None:
        _token_encryption = TokenEncryption()
    return _token_encryption


def encrypt_token(token: str) -> str:
    """Convenience function to encrypt a token"""
    return get_token_encryption().encrypt_token(token)


def decrypt_token(encrypted_token: str) -> str:
    """Convenience function to decrypt a token"""
    return get_token_encryption().decrypt_token(encrypted_token)
