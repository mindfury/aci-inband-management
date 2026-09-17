#!/usr/bin/env python3
"""Download APIC-matched acicobra/acimodel wheels and install them.

Cisco generates the Python object model alongside each APIC release.  That is
why this project cannot simply declare ``acicobra`` and ``acimodel`` as ordinary
PyPI dependencies: the model used by the script should match the controller it
will configure.  In the APIC GUI, the same files are linked from the built-in
Python SDK documentation page.  This helper automates that download page.
"""

from __future__ import annotations

import argparse
import html.parser
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests


class WheelLinks(html.parser.HTMLParser):
    """Extract wheel-file links from APIC's /cobra/_downloads/ HTML index."""

    def __init__(self) -> None:
        super().__init__()
        # Each discovered href is stored as text; no download occurs here.
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        # APIC returns a simple directory-style HTML page.  We only care about
        # <a href="...whl"> links and ignore eggs/parent-directory links.
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.endswith(".whl"):
                self.links.append(href)


def main() -> int:
    """Parse options, discover both wheels, download, and optionally pip install."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apic", required=True, help="APIC base URL, for example https://apic01")
    p.add_argument("--wheel-dir", default="cobra-whls")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--download-only", action="store_true")
    args = p.parse_args()

    # rstrip avoids producing //cobra when the operator supplies a trailing /.
    base = args.apic.rstrip("/") + "/cobra/_downloads/"

    # Certificate verification is the default.  --insecure is intended for a
    # controlled lab or a temporary bootstrap before the APIC CA is trusted.
    verify = not args.insecure

    # First request: retrieve only the HTML index so we can discover the exact
    # versioned filenames published by this APIC.
    response = requests.get(base, timeout=30, verify=verify)
    response.raise_for_status()
    links = WheelLinks()
    links.feed(response.text)

    # acicobra supplies login/query/commit mechanics.  acimodel supplies the
    # generated classes such as fv.BD and mgmt.InB.  Both are required.
    selected = []
    for prefix in ("acicobra-", "acimodel-"):
        candidates = sorted(href for href in links.links if Path(href).name.startswith(prefix))
        if not candidates:
            raise SystemExit(f"no {prefix}*.whl found at {base}")
        selected.append(candidates[-1])

    # Wheels stay in a Git-ignored directory: Cisco's generated packages should
    # not be committed to the repository.
    wheel_dir = Path(args.wheel_dir)
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheels = []
    for href in selected:
        destination = wheel_dir / Path(href).name
        # Stream in 1 MiB pieces instead of holding the whole wheel in memory.
        with requests.get(urljoin(base, href), timeout=120, verify=verify, stream=True) as wheel:
            wheel.raise_for_status()
            with destination.open("wb") as output:
                for chunk in wheel.iter_content(1024 * 1024):
                    output.write(chunk)
        wheels.append(destination)
        print(f"downloaded {destination}")

    if not args.download_only:
        # Use the same Python interpreter that launched this helper.  When the
        # operator activated .venv first, installation therefore lands in that
        # virtual environment rather than system Python.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *map(str, wheels)],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
