"""Custom exceptions for ProtonCalBridge."""


class ProtonCalBridgeError(Exception):
    pass


class IMAPConnectionError(ProtonCalBridgeError):
    pass


class IMAPAuthenticationError(IMAPConnectionError):
    pass


class CalDAVError(ProtonCalBridgeError):
    pass


class CalDAVAuthenticationError(CalDAVError):
    pass


class LLMError(ProtonCalBridgeError):
    pass


class LLMParseError(LLMError):
    pass


class ConfigurationError(ProtonCalBridgeError):
    pass


class DatabaseError(ProtonCalBridgeError):
    pass
