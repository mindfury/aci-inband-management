#!/usr/bin/env python3
"""Download APIC-matched acicobra/acimodel wheels and install them."""

from __future__ import annotations

import argparse
import html.parser
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests


class WheelLinks(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.endswith(".whl"):
                self.links.append(href)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apic", required=True, help="APIC base URL, for example https://apic01")
    p.add_argument("--wheel-dir", default="cobra-whls")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--download-only", action="store_true")
    args = p.parse_args()

    base = args.apic.rstrip("/") + "/cobra/_downloads/"
    verify = not args.insecure
    response = requests.get(base, timeout=30, verify=verify)
    response.raise_for_status()
    links = WheelLinks()
    links.feed(response.text)

    selected = []
    for prefix in ("acicobra-", "acimodel-"):
        candidates = sorted(href for href in links.links if Path(href).name.startswith(prefix))
        if not candidates:
            raise SystemExit(f"no {prefix}*.whl found at {base}")
        selected.append(candidates[-1])

    wheel_dir = Path(args.wheel_dir)
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheels = []
    for href in selected:
        destination = wheel_dir / Path(href).name
        with requests.get(urljoin(base, href), timeout=120, verify=verify, stream=True) as wheel:
            wheel.raise_for_status()
            with destination.open("wb") as output:
                for chunk in wheel.iter_content(1024 * 1024):
                    output.write(chunk)
        wheels.append(destination)
        print(f"downloaded {destination}")

    if not args.download_only:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *map(str, wheels)],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

