"""Command-line entry point."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from .cobra_apply import apply, connect, verify
from .config import ConfigError, load_config, plan


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Provision ACI 5.2 in-band management")
    p.add_argument("--config", required=True, help="path to JSON configuration")
    p.add_argument("--apic", default=os.getenv("ACI_APIC"), help="APIC URL")
    p.add_argument("--username", default=os.getenv("ACI_USERNAME", "admin"))
    p.add_argument("--password-env", default="ACI_PASSWORD")
    p.add_argument("--plan", action="store_true", help="validate and print plan; do not connect")
    p.add_argument("--insecure", action="store_true", help="disable TLS certificate validation")
    p.add_argument(
        "--confirm",
        action="store_true",
        help="required acknowledgement for a configuration-changing commit",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        desired = plan(config)
        if args.plan:
            print(json.dumps(desired, indent=2))
            return 0
        if not args.confirm:
            raise ConfigError("refusing to change APIC without --confirm; run --plan first")
        if not args.apic:
            raise ConfigError("--apic or ACI_APIC is required")
        password = os.getenv(args.password_env) or getpass.getpass("APIC password: ")
        directory = connect(args.apic, args.username, password, verify_ssl=not args.insecure)
        actual_version = directory.session.version or ""
        if not actual_version.startswith(config.apic_version):
            raise ConfigError(
                f"APIC reported {actual_version!r}, but configuration targets "
                f"{config.apic_version!r}; refusing to commit"
            )
        apply(directory, config)
        verified = verify(directory, config)
        print(json.dumps({"status": "committed", "verified_dns": verified}, indent=2))
        return 0
    except (ConfigError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
