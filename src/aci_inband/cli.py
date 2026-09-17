"""Small command-line wrapper around validation, Cobra login, and commit.

For a GUI user, ``main`` is the equivalent of: review every form, log in, check
the controller version, click Submit, and reopen the objects to verify them.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from .cobra_apply import apply, connect, verify
from .config import ConfigError, load_config, plan


def parser() -> argparse.ArgumentParser:
    """Define command-line fields and their environment-variable alternatives."""
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
    """Run plan mode or the guarded configuration-changing workflow."""
    args = parser().parse_args(argv)
    try:
        # Parse and validate first.  A bad VLAN, IP, or name fails here before
        # credentials are requested or an APIC connection is attempted.
        config = load_config(args.config)
        desired = plan(config)

        # Plan mode is read-only and offline: print the intended DNs and exit.
        if args.plan:
            print(json.dumps(desired, indent=2))
            return 0

        # Requiring a separate flag prevents an omitted --plan from becoming an
        # accidental production change.  This is the CLI equivalent of a GUI
        # confirmation dialog, but is suitable for automation/change records.
        if not args.confirm:
            raise ConfigError("refusing to change APIC without --confirm; run --plan first")
        if not args.apic:
            raise ConfigError("--apic or ACI_APIC is required")
        # Never put the APIC password in config.json or command history.  Read it
        # from the selected environment variable or prompt without echoing it.
        password = os.getenv(args.password_env) or getpass.getpass("APIC password: ")
        directory = connect(args.apic, args.username, password, verify_ssl=not args.insecure)

        # aaaLogin returns the running APIC version.  Stop before POST if this is
        # not a 5.2 controller matching the model targeted by the repository.
        actual_version = directory.session.version or ""
        if not actual_version.startswith(config.apic_version):
            raise ConfigError(
                f"APIC reported {actual_version!r}, but configuration targets "
                f"{config.apic_version!r}; refusing to commit"
            )
        # Build the managed-object tree and send the configuration request.
        apply(directory, config)

        # Read the anchor objects back by DN.  Physical reachability is validated
        # separately using the checklist in README.md.
        verified = verify(directory, config)
        print(json.dumps({"status": "committed", "verified_dns": verified}, indent=2))
        return 0
    except (ConfigError, RuntimeError) as exc:
        # Expected operator/configuration failures get one concise message and a
        # nonzero exit code that shell scripts and CI systems can recognize.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
