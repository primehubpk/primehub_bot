"""Master command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from rehan_bot.app.bootstrap import build_container
from rehan_bot.app.lifecycle import Lifecycle
from rehan_bot.app.routines import RoutineRunner
from rehan_bot.config import get_settings
from rehan_bot.notifications.whatsapp import build_web_sender
from rehan_bot.notifications.whatsapp_web import safe_print
from rehan_bot.observability.logging import configure_logging

DEFAULT_BANGLES_ASSETS = r"C:\Users\M.TT\Desktop\ustad-bot\Bangles_Assets"


def build_parser() -> argparse.ArgumentParser:
    """Build the application CLI parser."""

    parser = argparse.ArgumentParser(
        prog="rehan_bot",
        description=(
            "M&P logistics automation engine"
        ),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ---------------------------------------------------------
    # SCHEDULE
    # ---------------------------------------------------------

    sub.add_parser(
        "schedule",
        help="Run scheduled logistics routines.",
    )

    # ---------------------------------------------------------
    # TRACK
    # ---------------------------------------------------------

    track_parser = sub.add_parser(
        "track",
        help="Check one or more M&P tracking numbers.",
    )

    track_parser.add_argument(
        "tracking_numbers",
        nargs="*",
        help=(
            "Tracking/consignment numbers. "
            "If omitted, TRACKING_NUMBERS from .env "
            "will be used."
        ),
    )

    # ---------------------------------------------------------
    # RECONCILE
    # ---------------------------------------------------------

    sub.add_parser(
        "reconcile",
        help="Run COD reconciliation.",
    )

    # ---------------------------------------------------------
    # SHIPPER ADVICE
    # ---------------------------------------------------------

    sub.add_parser(
        "shipper-advice",
        help="Check pending shipper advice.",
    )

    # ---------------------------------------------------------
    # REPORT
    # ---------------------------------------------------------

    report_parser = sub.add_parser(
        "report",
        help="Generate the daily parcel summary and send it over WhatsApp.",
    )
    report_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the WhatsApp-formatted report without sending it.",
    )

    sub.add_parser(
        "daily",
        help=(
            "Track configured parcels, send the 11:00 WhatsApp daily "
            "report, then shut the browsers down cleanly."
        ),
    )

    # ---------------------------------------------------------
    # WHATSAPP
    # ---------------------------------------------------------

    sub.add_parser(
        "whatsapp-login",
        help=(
            "Open WhatsApp Web in a visible browser and link "
            "this device by scanning the QR code once."
        ),
    )

    whatsapp_test = sub.add_parser(
        "whatsapp-test",
        help="Send a test message to the configured WhatsApp number.",
    )

    whatsapp_test.add_argument(
        "--text",
        default="Rehan Bot WhatsApp Web test message.",
        help="Message body to send.",
    )

    # ---------------------------------------------------------
    # PRIMEHUB BULK UPLOAD
    # ---------------------------------------------------------

    primehub_upload = sub.add_parser(
        "primehub-upload",
        help="Parse product folders and upload them to PrimeHub (R2 + API).",
    )
    primehub_upload.add_argument(
        "--dir",
        dest="products_dir",
        default="",
        help="Product folder or parent directory of product folders.",
    )
    primehub_upload.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print JSON without uploading images or creating products.",
    )
    primehub_upload.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many NEW or modified folders (skips catalog_state matches).",
    )
    primehub_upload.add_argument(
        "--no-live-metadata",
        action="store_true",
        help="Skip GET /api/v1/store/metadata even if an API key is configured.",
    )
    primehub_upload.add_argument(
        "--base-url",
        default="",
        help="Override WEBSITE_URL for this run (e.g. a Vercel preview).",
    )
    primehub_upload.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Optional cap on how many folder images become Set cards. Default is every image.",
    )
    primehub_upload.add_argument(
        "--force",
        action="store_true",
        help="Re-upsert already-synced folders instead of skipping them.",
    )

    catalog_sync = sub.add_parser(
        "catalog-sync",
        aliases=["sync"],
        help="Sync local product folders to PrimeHub (delta-only, with catalog memory).",
    )
    catalog_sync.add_argument(
        "--dir",
        dest="products_dir",
        default=DEFAULT_BANGLES_ASSETS,
        help=(
            "Root of nested product folders. "
            f"Default: {DEFAULT_BANGLES_ASSETS}"
        ),
    )
    catalog_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect new/changed folders without uploading.",
    )
    catalog_sync.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many NEW or modified folders (skips already-synced ones).",
    )
    catalog_sync.add_argument(
        "--base-url",
        default="",
        help="Override WEBSITE_URL for this run (e.g. a Vercel preview).",
    )
    catalog_sync.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Optional cap on how many folder images become Set cards. Default is every image.",
    )
    catalog_sync.add_argument(
        "--force",
        action="store_true",
        help="Re-upsert already-synced folders instead of skipping them.",
    )
    catalog_sync.add_argument(
        "--edit-only",
        action="store_true",
        help=(
            "Check each design; heal FAIL only; split missed collages. "
            "Does not upload. Does not recrop every photo."
        ),
    )

    for alias, help_text in (
        (
            "edit",
            "Same as sync --edit-only: check/heal crops, no upload.",
        ),
        (
            "upload",
            "Same as sync: upload new folders only, skip already live.",
        ),
    ):
        extra = sub.add_parser(alias, help=help_text)
        extra.add_argument(
            "--dir",
            dest="products_dir",
            default=DEFAULT_BANGLES_ASSETS,
            help=f"Default: {DEFAULT_BANGLES_ASSETS}",
        )

    catalog_repair = sub.add_parser(
        "catalog-repair",
        help="Fix live product categories and wholesale flags without re-uploading images.",
    )
    catalog_repair.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Firestore patches without writing them.",
    )

    return parser


def _configured_tracking_numbers(
    configured: str | None,
) -> tuple[str, ...]:
    """Parse TRACKING_NUMBERS from .env."""
    if not configured:
        return ()

    return tuple(
        value.strip()
        for value in configured.split(",")
        if value.strip()
    )


def _whatsapp_command(command: str, settings: object, text: str) -> int:
    """Run WhatsApp linking/verification without booting the portal stack."""

    configure_logging(
        Path(getattr(settings, "log_file", "runtime/logs/rehan_bot.log"))
    )

    sender = build_web_sender(settings)

    if sender is None:
        print(
            "WhatsApp Web is not configured.\n\n"
            "Set these in .env:\n"
            "  WHATSAPP_MODE=web\n"
            "  WHATSAPP_PHONE=923001234567   (your own number, no '+')"
        )
        return 1

    if command == "whatsapp-login":
        return 0 if sender.link() else 1

    return 0 if sender.send(text) else 1


def _primehub_upload_command(args: argparse.Namespace, settings: object) -> int:
    """Parse product folders; optionally upload images and create products."""

    configure_logging(
        Path(getattr(settings, "log_file", "runtime/logs/rehan_bot.log"))
    )

    from rehan_bot.primehub.uploader import dumps_report, upload_products

    raw_dir = str(getattr(args, "products_dir", "") or "").strip()
    root = Path(raw_dir) if raw_dir else Path(
        getattr(settings, "primehub_products_dir", "") or ""
    )
    if not raw_dir and not str(root):
        safe_print(
            "No product directory supplied.\n\n"
            "Use:\n"
            "  python main.py primehub-upload --dir "
            "\"ustad-bot/Bangles_Assets/.../20Dozenbox_price_1200_28\" --dry-run"
        )
        return 1

    report = upload_products(
        root,
        settings,  # type: ignore[arg-type]
        dry_run=bool(getattr(args, "dry_run", False)),
        limit=getattr(args, "limit", None),
        fetch_live_metadata=not bool(getattr(args, "no_live_metadata", False)),
        base_url=str(getattr(args, "base_url", "") or "").strip() or None,
        force=bool(getattr(args, "force", False)),
        max_images=getattr(args, "max_images", None),
    )
    safe_print(dumps_report(report))
    return 0 if not report.errors else 1


def _catalog_sync_command(args: argparse.Namespace, settings: object) -> int:
    """Walk product folders and upload only new or changed photos."""

    configure_logging(
        Path(getattr(settings, "log_file", "runtime/logs/rehan_bot.log"))
    )

    from rehan_bot.primehub.catalog_sync import sync_catalog

    raw_dir = str(getattr(args, "products_dir", "") or "").strip()
    root = Path(
        raw_dir
        or getattr(settings, "primehub_products_dir", "")
        or DEFAULT_BANGLES_ASSETS
    )
    if not root.exists():
        safe_print(f"Product directory does not exist: {root}")
        return 1

    base_url = str(getattr(args, "base_url", "") or "").strip() or None
    report = sync_catalog(
        root,
        settings,  # type: ignore[arg-type]
        dry_run=bool(getattr(args, "dry_run", False)),
        limit=getattr(args, "limit", None),
        base_url=base_url,
        force=bool(getattr(args, "force", False)),
        max_images=getattr(args, "max_images", None),
        edit_only=bool(getattr(args, "edit_only", False)),
    )
    host = (base_url or str(getattr(settings, "primehub_base_url", "") or "")).rstrip("/")
    safe_print(report.summary_line())
    skipped = [item for item in report.folders if item.action == "skip"]
    if skipped:
        names = ", ".join(Path(item.folder).name for item in skipped[:12])
        extra = f", +{len(skipped) - 12} more" if len(skipped) > 12 else ""
        safe_print(f"  skipped {len(skipped)} synced folder(s): {names}{extra}")
    for item in report.folders:
        if item.action == "skip":
            continue
        extra = f" slug={item.slug}" if item.slug else ""
        safe_print(f"  {item.action}: {item.folder} ({item.processed} image(s)){extra}")
        for image in item.images:
            before = int(image.get("original_bytes") or 0)
            after = int(image.get("bytes") or 0)
            ow = image.get("original_width") or "?"
            oh = image.get("original_height") or "?"
            width = image.get("width")
            height = image.get("height")
            safe_print(
                f"    {image.get('file')}: {ow}x{oh} {before / 1024:.0f} KB -> "
                f"{width}x{height} webp {after / 1024:.1f} KB "
                f"(crop=1:1 ev={image.get('ev')} margin={image.get('margin')} "
                f"style={image.get('style')})"
            )
            if image.get("url"):
                safe_print(f"    url: {image['url']}")
            product_id = str(image.get("product_id") or "")
            if host and product_id:
                safe_print(f"    product: {host}/product/{product_id}")
            elif image.get("title"):
                safe_print(f"    card: {image.get('title')}")
        if host and item.product_id and not any(img.get("product_id") for img in item.images):
            safe_print(f"  product: {host}/product/{item.product_id}")
    for error in report.errors:
        safe_print(f"  error: {error}")
    return 0 if not report.errors else 1


def _catalog_repair_command(args: argparse.Namespace, settings: object) -> int:
    configure_logging(
        Path(getattr(settings, "log_file", "runtime/logs/rehan_bot.log"))
    )
    from rehan_bot.primehub.repair_storefront import repair_storefront_products

    dry_run = bool(getattr(args, "dry_run", False))
    report = repair_storefront_products(settings, dry_run=dry_run)  # type: ignore[arg-type]
    prefix = "dry-run " if dry_run else ""
    safe_print(
        f"{prefix}scanned {report.scanned} folders: "
        f"{report.updated} updated, {report.relocated} relocated, "
        f"{report.skipped} already correct."
    )
    for error in report.errors:
        safe_print(f"  error: {error}")
    return 0 if not report.errors else 1


def main() -> int:
    """Run the selected CLI command."""

    args = build_parser().parse_args()

    settings = get_settings()

    if args.command in {"whatsapp-login", "whatsapp-test"}:
        return _whatsapp_command(
            args.command,
            settings,
            getattr(args, "text", ""),
        )

    if args.command == "primehub-upload":
        return _primehub_upload_command(args, settings)

    if args.command in {"catalog-sync", "sync", "edit", "upload"}:
        if args.command == "edit":
            args.edit_only = True
            args.force = False
            args.dry_run = False
            args.limit = None
            args.base_url = ""
            args.max_images = None
        elif args.command == "upload":
            args.edit_only = False
            args.force = False
            args.dry_run = False
            args.limit = None
            args.base_url = ""
            args.max_images = None
        return _catalog_sync_command(args, settings)

    if args.command == "catalog-repair":
        return _catalog_repair_command(args, settings)

    container = build_container(settings)

    configured_numbers = (
        _configured_tracking_numbers(
            settings.tracking_numbers
        )
    )

    routines = RoutineRunner(
        portal=container.portal,
        sessions=container.sessions,
        report=container.report,
        notifications=container.notifications,
        settings=settings,
        tracking_numbers=configured_numbers,
        payment_statement=(
            settings.payment_statement_file
        ),
        ai_recovery=container.ai_recovery,
    )

    lifecycle = Lifecycle(
        (
            container.close,
        )
    )

    lifecycle.install_signal_handlers()

    try:
        # =====================================================
        # TRACK
        # =====================================================

        if args.command == "track":
            command_numbers = tuple(
                value.strip()
                for value in args.tracking_numbers
                if value.strip()
            )

            if command_numbers:
                tracking_numbers = command_numbers
            else:
                tracking_numbers = configured_numbers

            if not tracking_numbers:
                raise ValueError(
                    "No tracking number supplied.\n\n"
                    "Use:\n"
                    "  python main.py track 123456789\n\n"
                    "or put numbers in .env:\n"
                    "  TRACKING_NUMBERS="
                    "123456789,987654321"
                )

            count = routines.track(
                tracking_numbers
            )

            print()
            print(
                "========================================"
            )
            print(
                "        M&P TRACKING COMPLETE"
            )
            print(
                "========================================"
            )
            print(
                f"Checked: {count}"
            )
            print(
                "Numbers: "
                + ", ".join(tracking_numbers)
            )
            print(
                "========================================"
            )
            print()

            return 0

        # =====================================================
        # DAILY (track configured numbers + WhatsApp report)
        # =====================================================

        if args.command == "daily":
            routines.morning()
            return 0

        # =====================================================
        # SCHEDULE
        # =====================================================

        if args.command == "schedule":
            container.scheduler.add_routines(
                morning=routines.morning,
                periodic=routines.periodic,
                evening=routines.evening,
            )

            container.scheduler.start()

            print()
            print(
                "========================================"
            )
            print(
                "       REHAN BOT SCHEDULER RUNNING"
            )
            print(
                "========================================"
            )
            print(
                "Morning routine : 11:00 PKT"
            )
            print(
                "Evening routine : 20:00 PKT"
            )
            print(
                "Press CTRL+C to stop."
            )
            print(
                "========================================"
            )
            print()

            lifecycle.wait()

            return 0

        # =====================================================
        # REPORT
        # =====================================================

        if args.command == "report":
            summary = container.report.build()
            if getattr(args, "dry_run", False):
                safe_print(summary.to_whatsapp())
                return 0
            container.report.send_whatsapp(summary)
            return 0

        # =====================================================
        # RECONCILIATION
        # =====================================================

        if args.command == "reconcile":
            routines.evening()
            return 0

        # =====================================================
        # SHIPPER ADVICE
        # =====================================================

        if args.command == "shipper-advice":
            routines.periodic()
            return 0

        raise RuntimeError(
            f"Unsupported command: {args.command}"
        )

    finally:
        lifecycle.shutdown_quietly()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )