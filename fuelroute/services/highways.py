"""Parse and normalize US highway references from free-text addresses.

Used to cross-check candidate stations against the route's actual
highways (obtained from the same single OSRM call that returns the
route itself) as a ranking signal — never a hard filter, since not
every address embeds a parseable highway.
"""

import re

_HIGHWAY_PATTERN = re.compile(
    r'\b((?:I|US|SR|SH|HWY|ST|RT)[\s-]*\d+)(?![\d])',
    re.IGNORECASE,
)

_EXIT_PATTERN = re.compile(r'\bEXIT[\s#-]*(\d+[\s-]?[A-Z]?)\b', re.IGNORECASE)


def normalize_highway(ref: str) -> str:
    """Canonicalize a highway ref so differently-formatted refs compare equal.

    "I-80", "I 80" and OSRM's own "I 80" step ref all normalize to "I80",
    so an address-parsed ref can be compared directly against a route
    step's ref.
    """
    return re.sub(r'[\s-]+', '', ref.strip().upper())


def parse_highway(address: str) -> str:
    """Return the first normalized highway ref found in `address`, or ''.

    Roughly 98% of the supplied dataset's addresses embed one, e.g.
    "I-44, EXIT 283 & US-69" -> "I44".
    """
    match = _HIGHWAY_PATTERN.search(address)
    return normalize_highway(match.group(1)) if match else ''


def parse_exit(address: str) -> str:
    """Return the normalized exit number in `address`, or ''.

    "I-44, EXIT 283 & US-69" -> "283"; "EXIT 144-B" -> "144B". Used to
    look up a station's position against `data/highway_exits.csv`
    (real motorway_junction coordinates), a tier more precise than the
    city-centroid gazetteer for the ~55% of addresses that embed one.
    """
    match = _EXIT_PATTERN.search(address)
    return re.sub(r'[\s-]+', '', match.group(1).upper()) if match else ''


def parse_route_highways(refs: list[str]) -> set[str]:
    """Normalize OSRM step `ref` values into a set for membership checks.

    OSRM sometimes packs multiple refs into one string separated by
    semicolons (e.g. "I 90;US 20"); each part is normalized separately.
    """
    highways = set()
    for ref in refs:
        if not ref:
            continue
        for part in ref.split(';'):
            part = part.strip()
            if part:
                highways.add(normalize_highway(part))
    return highways
