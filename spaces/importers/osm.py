"""Conservative OSM facility mappings; see docs/data-sources.md for semantics."""
OUTDOOR_POSITIVE = {
    "yes", "parklet", "pedestrian_zone", "street", "sidewalk", "patio", "terrace",
    "balcony", "veranda", "roof", "garden", "beach", "courtyard", "separate",
}
# bs1363 is OSM's key for the Irish/UK domestic socket (IEC type G), the usual Dublin outlet.
MAINS_SOCKET_TYPES = {
    "typea", "typeb", "typec", "typed", "typee", "typef", "typeg", "typeh",
    "typei", "typej", "typek", "typel", "typem", "typen", "typeo", "schuko", "bs1363",
}


def parse_facilities(tags):
    values = {}
    issues = []

    def tokens(key):
        value = tags.get(key)
        return {part.strip().lower() for part in value.split(";")} if isinstance(value, str) else set()

    def boolean(key, positive=frozenset({"yes"})):
        if key not in tags:
            return None
        parts = tokens(key)
        if parts == {"no"}:
            return False
        if parts and parts <= positive:
            return True
        issues.append(f"{key}={tags[key]!r}: unsupported or conflicting value")
        return None

    def conditional(prefixes):
        return any(key.startswith(prefix) for key in tags for prefix in prefixes)

    def combine(evidence, field):
        known = {item for item in evidence if item is not None}
        if len(known) > 1:
            issues.append(f"{field}: conflicting tags")
            return None
        return next(iter(known)) if known else None

    for field, positive in (("indoor_seating", {"yes"}), ("outdoor_seating", OUTDOOR_POSITIVE)):
        values[field] = boolean(field, positive)
        if conditional((f"{field}:conditional", f"{field}:seasonal")):
            values[field] = None
            issues.append(f"{field}: conditional/seasonal availability retained as unknown")

    wifi_issue_start = len(issues)
    internet = tokens("internet_access")
    internet_value = None
    if "internet_access" in tags:
        allowed = {"wlan", "wired", "terminal", "yes", "public", "service", "no"}
        if not internet or not internet <= allowed or ("no" in internet and len(internet) > 1):
            issues.append("internet_access: unsupported or conflicting value")
        elif internet == {"no"}:
            internet_value = False
        elif "wlan" in internet:
            internet_value = True
        # Generic internet access and wired/terminal access do not establish Wi-Fi.
    values["has_wifi"] = combine([internet_value, boolean("wifi", {"yes", "free"})], "has_wifi")
    if len(issues) > wifi_issue_start:
        values["has_wifi"] = None
    if conditional(("internet_access:conditional", "wifi:conditional")):
        values["has_wifi"] = None
        issues.append("has_wifi: conditional access retained as unknown")

    power_issue_start = len(issues)
    power = boolean("power_supply")
    sockets = []
    for socket_type in MAINS_SOCKET_TYPES:
        key = f"socket:{socket_type}"
        if key in tags:
            value = tags[key]
            if isinstance(value, str) and (value.lower() == "yes" or (value.isdigit() and int(value) > 0)):
                sockets.append(True)
            elif str(value).lower() not in {"no", "0"}:
                issues.append(f"{key}={value!r}: unsupported socket count")
    # A zero count for one socket type does not prove all socket types absent.
    values["has_outlets"] = combine([power, *sockets], "has_outlets")
    if len(issues) > power_issue_start:
        values["has_outlets"] = None
    if conditional(("power_supply:conditional", "power_supply:schedule")) or any(
        key.startswith("socket:") and key.endswith(":conditional") for key in tags
    ):
        values["has_outlets"] = None
        issues.append("has_outlets: conditional availability retained as unknown")

    values["laptop_allowed"] = boolean("laptop")
    if conditional(("laptop:conditional",)):
        values["laptop_allowed"] = None
        issues.append("laptop: conditional permission retained as unknown")
    return values, issues
