"""Custom exceptions for mail_events_to_caldav."""


class MailEventsToCaldavError(Exception):
    pass


class IMAPConnectionError(MailEventsToCaldavError):
    pass


class IMAPAuthenticationError(IMAPConnectionError):
    pass


class CalDAVError(MailEventsToCaldavError):
    pass


class CalDAVAuthenticationError(CalDAVError):
    pass


class LLMError(MailEventsToCaldavError):
    pass


class LLMParseError(LLMError):
    pass


class ConfigurationError(MailEventsToCaldavError):
    pass


class DatabaseError(MailEventsToCaldavError):
    pass
