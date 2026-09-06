"""Portal state definitions."""
from enum import Enum

class PortalState(str, Enum):
    """High-level deterministic portal states."""
    AUTHENTICATED = "authenticated"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_DETECTED = "captcha_detected"
    PORTAL_MAINTENANCE = "portal_maintenance"
    TIMEOUT = "timeout"
