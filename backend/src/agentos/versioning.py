"""Version comparison utilities for CaberOS auto-update (v0.1.3).

Provides semantic version comparison for the updater to determine whether
a GitHub release is newer than the installed version.
"""

import re


def parse_version(version: str) -> tuple[int, int, int, str | None]:
    """Parse a semver string into (major, minor, patch, prerelease).

    Examples:
        "0.1.3" → (0, 1, 3, None)
        "0.1.3-beta" → (0, 1, 3, "beta")
        "1.2.3" → (1, 2, 3, None)
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?$", version)
    if not match:
        raise ValueError(f"Invalid version format: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two semantic version strings.

    Returns:
        1 if v1 > v2
        0 if v1 == v2
        -1 if v1 < v2

    Prerelease versions are considered lower than the same version without
    a prerelease suffix (e.g. "0.1.3-beta" < "0.1.3").
    """
    major1, minor1, patch1, pre1 = parse_version(v1)
    major2, minor2, patch2, pre2 = parse_version(v2)

    # Compare major.minor.patch
    for a, b in [(major1, major2), (minor1, minor2), (patch1, patch2)]:
        if a > b:
            return 1
        if a < b:
            return -1

    # Same major.minor.patch — compare prerelease
    # No prerelease > has prerelease (release > prerelease)
    if pre1 is None and pre2 is None:
        return 0
    if pre1 is None and pre2 is not None:
        return 1
    if pre1 is not None and pre2 is None:
        return -1
    # Both have prerelease — lexicographic comparison
    if pre1 > pre2:
        return 1
    if pre1 < pre2:
        return -1
    return 0
