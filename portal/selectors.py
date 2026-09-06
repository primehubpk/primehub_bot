"""Centralized deterministic M&P CP-Light portal selectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectorSet:
    """Ordered locator candidates."""

    candidates: tuple[str, ...]


class PortalSelectors:
    """M&P CP-Light selector hierarchy.

    Selectors deliberately use multiple independent strategies:
    - semantic HTML attributes
    - labels/placeholders
    - visible button text
    - broad input fallbacks

    The login page is a JavaScript application, so no single DOM selector
    is treated as authoritative.
    """

    # =========================================================
    # LOGIN — USERNAME
    # =========================================================

    USERNAME = SelectorSet(
        (
            'input[name="username"]',
            'input[name="userName"]',
            'input[name="Username"]',
            'input[id="username"]',
            'input[id="userName"]',
            'input[id="Username"]',
            'input[placeholder*="username" i]',
            'input[placeholder*="user name" i]',
            'input[aria-label*="username" i]',
            'input[aria-label*="user name" i]',
            'input[type="text"]',
            'input:not([type])',
        )
    )

    # =========================================================
    # LOGIN — PASSWORD
    # =========================================================

    PASSWORD = SelectorSet(
        (
            'input[name="password"]',
            'input[name="Password"]',
            'input[id="password"]',
            'input[id="Password"]',
            'input[placeholder*="password" i]',
            'input[aria-label*="password" i]',
            'input[type="password"]',
        )
    )

    # =========================================================
    # LOGIN — SUBMIT
    # =========================================================

    SUBMIT = SelectorSet(
        (
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Sign in")',
            'button:has-text("SIGN IN")',
            'button:has-text("Login")',
            'button:has-text("Log in")',
            'input[value*="Sign In" i]',
            'input[value*="Login" i]',
        )
    )

    # =========================================================
    # AUTHENTICATED STATE
    # =========================================================

    AUTHENTICATED_MARKERS = SelectorSet(
        (
            '[data-testid="dashboard"]',
            '[aria-label="Dashboard"]',
            '[data-testid*="dashboard" i]',
            '[id*="dashboard" i]',
            '[class*="dashboard" i]',
            'a:has-text("Dashboard")',
            'button:has-text("Dashboard")',
            'text=Dashboard',
            'text=Welcome',
            'text=Welcome Back',
            'text=Logout',
            'text=Log out',
            'text=Sign Out',
            'text=Sign out',
        )
    )

    # =========================================================
    # LOGIN STATE
    # =========================================================

    LOGIN_MARKERS = SelectorSet(
        (
            'input[name="username"]',
            'input[name="userName"]',
            'input[id="username"]',
            'input[id="userName"]',
            'input[placeholder*="username" i]',
            'input[aria-label*="username" i]',
            'input[type="password"]',
            'button:has-text("Sign In")',
            'button:has-text("Sign in")',
            'button:has-text("Login")',
        )
    )

    # =========================================================
    # CAPTCHA
    # =========================================================

    CAPTCHA_MARKERS = SelectorSet(
        (
            'iframe[src*="captcha" i]',
            'iframe[src*="recaptcha" i]',
            'iframe[title*="captcha" i]',
            '[id*="captcha" i]',
            '[class*="captcha" i]',
            '[name*="captcha" i]',
            '[id*="recaptcha" i]',
            '[class*="recaptcha" i]',
            'text=CAPTCHA',
            'text=Captcha',
            'text=Verify you are human',
            'text=I am not a robot',
        )
    )

    # =========================================================
    # MAINTENANCE / UNAVAILABLE
    # =========================================================

    MAINTENANCE_MARKERS = SelectorSet(
        (
            'text=Maintenance',
            'text=Service Unavailable',
            'text=temporarily unavailable',
            'text=Temporarily Unavailable',
            'text=under maintenance',
            'text=Under Maintenance',
            '[data-testid="maintenance"]',
            '[id*="maintenance" i]',
            '[class*="maintenance" i]',
        )
    )

    # =========================================================
    # TRACKING
    # =========================================================

    TRACKING_INPUT = SelectorSet(
        (
            'input[name="trackingNumber"]',
            'input[name="tracking_number"]',
            'input[name="consignment"]',
            'input[name="consignmentNumber"]',
            'input[name="cn"]',
            'input[id="trackingNumber"]',
            'input[id="tracking_number"]',
            'input[id="consignment"]',
            'input[id="consignmentNumber"]',
            'input[placeholder*="tracking" i]',
            'input[placeholder*="consignment" i]',
            'input[placeholder*="CN" i]',
            'input[aria-label*="tracking" i]',
            'input[aria-label*="consignment" i]',
            'textarea[name*="cn" i]',
            'textarea[placeholder*="consignment" i]',
            'input[type="text"]',
        )
    )

    TRACKING_SUBMIT = SelectorSet(
        (
            'button[type="submit"]',
            'button:has-text("Track")',
            'button:has-text("TRACK")',
            'button:has-text("Search")',
            'button:has-text("SEARCH")',
            'button:has-text("Submit")',
            'input[type="submit"]',
            'input[value*="Track" i]',
            'input[value*="Search" i]',
        )
    )

    # The tracking_2 screen answers over AJAX behind a "Please Wait" overlay.
    # Every candidate is probed for visibility first, so entries that never
    # render simply cost nothing.
    LOADER_OVERLAY = SelectorSet(
        (
            ".blockUI",
            ".blockOverlay",
            ".blockMsg",
            "#loader",
            ".loader",
            "#loading",
            ".loading",
            "#divLoading",
            "#overlay",
            ".loading-overlay",
            ".spinner-border",
            ".spinner",
            '[id*="please" i]',
            '[class*="please" i]',
            '[id*="wait" i]',
            '[class*="wait" i]',
            '[id*="loading" i]',
            '[class*="loading" i]',
            "text=Please Wait",
            "text=Please wait",
        )
    )

    # tracking_2 is a React screen: the answer is a div timeline plus readonly
    # detail inputs, not a table.
    TRACKING_TIMELINE_ITEM = SelectorSet(
        (
            ".timeline .timeline-item",
            ".timeline-item",
        )
    )

    TRACKING_TIMELINE_TIMESTAMP = SelectorSet((".timestamp",))

    TRACKING_TIMELINE_STATUS = SelectorSet(
        (
            ".timeline-right > div:not(.location):not(.description)",
            ".timeline-right div:first-child",
        )
    )

    TRACKING_TIMELINE_LOCATION = SelectorSet((".location",))

    TRACKING_DETAIL_LABEL = SelectorSet(
        (
            "label.input-label",
            ".shipment-section label",
        )
    )

    TRACKING_RESULT_CONTAINER = SelectorSet(
        (
            ".timeline-item",
            ".timestamp",
            ".shipment-section",
            "#tracking_detail",
            ".tracking-result",
            ".table-responsive table tbody tr",
            "table tbody tr",
        )
    )

    TRACKING_NOT_FOUND = SelectorSet(
        (
            ".dataTables_empty",
            "text=No record found",
            "text=No Record Found",
            "text=NO RECORD FOUND",
            "text=No records found",
            "text=No data available",
            "text=No Data Available",
            "text=Record not found",
            "text=Invalid Tracking Number",
            "text=Invalid CN",
        )
    )

    TRACKING_STATUS = SelectorSet(
        (
            '[data-testid="tracking-status"]',
            '[data-testid*="tracking" i]',
            '[id*="tracking-status" i]',
            '[class*="tracking-status" i]',
            '[id*="trackingstatus" i]',
            '[class*="trackingstatus" i]',
            '[class*="shipment-status" i]',
            '[class*="shipmentstatus" i]',
            '.badge',
            '.badge-success',
            '.badge-info',
            '.badge-primary',
            '.badge-warning',
            '.badge-danger',
            'table tbody tr td:nth-child(6)',
            'table tbody tr td:nth-child(5)',
            'table tbody tr td:nth-child(4)',
            'table tbody tr td',
            '.table td',
            '.status',
            'div[class*="status" i]',
            'span[class*="status" i]',
        )
    )

    # =========================================================
    # SHIPPER ADVICE
    # =========================================================

    SHIPPER_ADVICE_PENDING = SelectorSet(
        (
            '[data-testid="shipper-advice-pending"]',
            '[data-testid*="shipper-advice" i]',
            '[id*="shipper-advice" i]',
            '[class*="shipper-advice" i]',
            'text=Shipper Advice',
            'text=Pending Advice',
        )
    )

    SHIPPER_ADVICE_INPUT = SelectorSet(
        (
            'textarea[name="advice"]',
            'textarea[name="shipperAdvice"]',
            'textarea[id="advice"]',
            'textarea[id="shipperAdvice"]',
            'textarea[placeholder*="advice" i]',
            'textarea',
        )
    )

    SHIPPER_ADVICE_SUBMIT = SelectorSet(
        (
            'button[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("SUBMIT")',
            'button:has-text("Save")',
            'button:has-text("SAVE")',
        )
    )

    SHIPPER_ADVICE_SUCCESS = SelectorSet(
        (
            '[data-testid="success"]',
            '[role="alert"]',
            'text=Successfully',
            'text=Success',
            'text=Submitted',
            'text=Saved',
        )
    )

    SHIPPER_ADVICE_INSTRUCTION = SelectorSet(
        (
            'select[name*="advice" i]',
            'select[name*="instruction" i]',
            'select[id*="advice" i]',
            '[role="listbox"]',
            'text=Return to Shipper',
            'text=Re-attempt delivery',
            'text=Reattempt Delivery',
        )
    )

    SHIPPER_ADVICE_ROW = SelectorSet(
        (
            'table tbody tr',
            '[data-testid*="advice-row" i]',
            '.advice-row',
            '.pending-advice',
        )
    )

    # =========================================================
    # SIDEBAR / TRACKING NAVIGATION
    # =========================================================

    NAV_TRACKING_PARENT = SelectorSet(
        (
            'nav >> text=Tracking',
            '.sidebar >> text=Tracking',
            '[aria-haspopup] >> text=Tracking',
            'a:has-text("Tracking")',
            'button:has-text("Tracking")',
            'span:has-text("Tracking")',
        )
    )

    NAV_TRACKING_CHILD = SelectorSet(
        (
            'a[href*="/tracking" i]',
            'a[href*="tracking" i]',
            'a:has-text("Tracking")',
            'button:has-text("Tracking")',
            '[role="menuitem"]:has-text("Tracking")',
            'li:has-text("Tracking") a',
        )
    )

    # =========================================================
    # OVERLAYS / POPUPS
    # =========================================================

    OVERLAY_CLOSE = SelectorSet(
        (
            'button:has-text("Close")',
            'button:has-text("CLOSE")',
            'button:has-text("OK")',
            'button:has-text("Got it")',
            'button[aria-label*="close" i]',
            'button[aria-label*="dismiss" i]',
            '.modal button.close',
            '.popup button.close',
            '[class*="modal" i] button:has-text("×")',
            '[class*="overlay" i] button',
        )
    )

    # =========================================================
    # COD / PAYMENTS
    # =========================================================

    PAYMENTS_DOWNLOAD = SelectorSet(
        (
            'button:has-text("Download")',
            'a:has-text("Download")',
            'button:has-text("Export")',
            'a:has-text("Export")',
            'button:has-text("CSV")',
            'a:has-text("CSV")',
            'button:has-text("Excel")',
            'a[download]',
            'button[type="submit"]:has-text("Download")',
        )
    )

    PAYMENTS_TABLE_ROWS = SelectorSet(
        (
            'table tbody tr',
            '[data-testid*="payment-row" i]',
            '.payment-row',
            '.statement-row',
        )
    )
