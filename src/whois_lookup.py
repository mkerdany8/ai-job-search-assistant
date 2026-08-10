"""Domain registration lookup, used as a legitimacy-checking tool.

Two backends. RDAP over HTTPS is the primary one: it is the modern
replacement for the WHOIS protocol and returns structured JSON, so there is
nothing to regex. The system `whois` binary is the fallback for the ccTLDs
that RDAP bootstrap does not cover.

The important distinction this module preserves is between "this domain does
not exist" (a strong warning sign), "the registrant is hidden behind privacy
protection" (the default at most registrars, and no signal at all), and "the
lookup failed" (no information either way). Collapsing those three into one
'unknown' is what makes this kind of check useless.
"""

import datetime as dt
import logging
import re
import shutil
import subprocess
from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

RDAP_ENDPOINT = "https://rdap.org/domain/{domain}"
RDAP_TIMEOUT = 10
WHOIS_TIMEOUT = 15

# rdap.org sits behind Cloudflare, which serves a 403 challenge page to the
# default python-requests user agent. Identifying ourselves gets a real answer.
USER_AGENT = "aip444-application-advisor/1.0 (coursework project)"

# Tool schema handed to the LLM so it can decide which domains to check.
WHOIS_TOOL = {
    "type": "function",
    "function": {
        "name": "whois_lookup",
        "description": (
            "Look up the domain registration record for a domain name. Returns "
            "the registration date, expiry date, registrar, registrant "
            "organization, and country. Use this to check whether a company's "
            "website or the contact address on a job posting belongs to an "
            "established domain or one registered very recently. Pass a bare "
            "domain such as 'example.com', not a full URL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain to look up, for example 'rbc.com'.",
                }
            },
            "required": ["domain"],
            "additionalProperties": False,
        },
    },
}

# Second-level domains that are really public suffixes, so example.co.uk is
# the registrable name and co.uk is not. Not exhaustive, just the ones a
# Canadian job search actually runs into.
_MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
    "com.au", "net.au", "org.au", "edu.au",
    "co.nz", "co.jp", "co.in", "co.za", "co.kr", "co.il",
    "com.br", "com.mx", "com.sg", "com.hk", "com.cn", "com.tr",
    "gc.ca", "on.ca", "qc.ca", "ab.ca", "bc.ca",
}

# Registrars redact registrant details by default post-GDPR. These strings
# mean "hidden", not "fake".
_PRIVACY_MARKERS = (
    "redacted", "privacy", "private", "withheld", "not disclosed",
    "data protected", "domains by proxy", "whoisguard", "identity protect",
    "not available from registry", "statutory masking", "gdpr", "masked",
)

_NOT_FOUND_MARKERS = (
    "no match for", "not found", "no data found", "no entries found",
    "domain not found", "no object found", "status: free",
    "status: available", "no matching record",
)


class WhoisResult(BaseModel):
    """One domain registration record, or an explanation of why there isn't one."""

    domain: str
    found: bool = Field(description="False if the domain is not registered at all")
    registration_date: Optional[str] = Field(description="ISO date the domain was first registered, null if unavailable")
    age_days: Optional[int] = Field(description="Days since registration, computed locally. Null if the date is unavailable.")
    expiry_date: Optional[str] = Field(description="ISO date the registration expires, null if unavailable")
    registrar: Optional[str] = Field(description="Registrar name, null if unavailable")
    registrant_org: Optional[str] = Field(description="Registrant organization, null if redacted or unavailable")
    country: Optional[str] = Field(description="Registrant country code, null if redacted or unavailable")
    privacy_redacted: bool = Field(description="True if registrant details are hidden behind privacy protection")
    source: str = Field(description="Which backend answered: rdap, whois, or none")
    error: Optional[str] = Field(description="Why the lookup failed, null if it succeeded")


def normalize_domain(raw: str) -> str:
    """Reduce a URL, email address, or hostname to its registrable domain.

    'https://careers.rbc.com/jobs/1' and 'hr@careers.rbc.com' both become
    'rbc.com', which is what a registration lookup will actually answer for.
    """
    d = raw.strip().lower()
    if "@" in d:
        d = d.rsplit("@", 1)[1]
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split(":")[0].strip().strip(".")
    if d.startswith("www."):
        d = d[4:]

    parts = [p for p in d.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _parse_date(value: Optional[str]) -> Optional[dt.datetime]:
    """Parse the several date formats RDAP and whois servers hand back."""
    if not value:
        return None
    v = value.strip().rstrip(".")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(v)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%d-%b-%Y", "%Y.%m.%d", "%d/%m/%Y", "%d.%m.%Y",
    ):
        try:
            return dt.datetime.strptime(v, fmt)
        except ValueError:
            continue
    log.debug("Could not parse date %r", value)
    return None


def _age_days(when: Optional[dt.datetime]) -> Optional[int]:
    if when is None:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return (dt.datetime.utcnow() - when).days


def _is_privacy(value: Optional[str]) -> bool:
    if not value:
        return False
    low = value.lower()
    return any(m in low for m in _PRIVACY_MARKERS)


def _clean(value: Optional[str]) -> Optional[str]:
    """Drop values that are really privacy placeholders."""
    if not value or not value.strip():
        return None
    return None if _is_privacy(value) else value.strip()


def _vcard_field(entity: dict, field: str) -> Optional[str]:
    """Pull one field out of an RDAP entity's jCard array."""
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) < 2:
        return None
    for item in vcard[1]:
        if not isinstance(item, list) or len(item) < 4 or item[0] != field:
            continue
        value = item[3]
        if field == "adr" and isinstance(value, list):
            # Structured address: country is the last component.
            return str(value[-1]) if value and value[-1] else None
        if isinstance(value, str):
            return value
    return None


def _entity_by_role(entities: Any, role: str) -> Optional[dict]:
    if not isinstance(entities, list):
        return None
    for e in entities:
        if isinstance(e, dict) and role in (e.get("roles") or []):
            return e
    return None


def _from_rdap(domain: str) -> Optional[WhoisResult]:
    """Query RDAP. Returns None if RDAP cannot answer, so we fall back."""
    try:
        resp = requests.get(
            RDAP_ENDPOINT.format(domain=domain),
            timeout=RDAP_TIMEOUT,
            headers={"Accept": "application/rdap+json", "User-Agent": USER_AGENT},
        )
    except Exception as e:
        log.debug("RDAP request failed for %s: %s", domain, e)
        return None

    if resp.status_code == 404:
        # Ambiguous: either the domain is unregistered or the TLD has no RDAP
        # service. Let the whois fallback settle it.
        log.debug("RDAP 404 for %s, deferring to whois", domain)
        return None
    if resp.status_code != 200:
        log.debug("RDAP returned %d for %s", resp.status_code, domain)
        return None

    try:
        data = resp.json()
    except ValueError as e:
        log.debug("RDAP returned non-JSON for %s: %s", domain, e)
        return None

    events = {
        e.get("eventAction"): e.get("eventDate")
        for e in data.get("events", []) or []
        if isinstance(e, dict)
    }
    registered = _parse_date(events.get("registration"))
    expires = _parse_date(events.get("expiration"))

    registrar_entity = _entity_by_role(data.get("entities"), "registrar")
    registrar = _vcard_field(registrar_entity, "fn") if registrar_entity else None

    registrant_entity = _entity_by_role(data.get("entities"), "registrant")
    registrant_org = country = None
    if registrant_entity:
        registrant_org = _vcard_field(registrant_entity, "org") or _vcard_field(registrant_entity, "fn")
        country = _vcard_field(registrant_entity, "adr")

    redacted = bool(data.get("redacted")) or _is_privacy(registrant_org) or (
        registrant_entity is None and registered is not None
    )

    log.debug(
        "RDAP hit for %s: registered=%s registrar=%s redacted=%s",
        domain, registered.date() if registered else None, registrar, redacted,
    )
    return WhoisResult(
        domain=domain,
        found=True,
        registration_date=registered.date().isoformat() if registered else None,
        age_days=_age_days(registered),
        expiry_date=expires.date().isoformat() if expires else None,
        registrar=_clean(registrar),
        registrant_org=_clean(registrant_org),
        country=_clean(country),
        privacy_redacted=redacted,
        source="rdap",
        error=None,
    )


def _whois_field(text: str, *labels: str) -> Optional[str]:
    """First non-empty value for any of these whois field labels.

    Horizontal whitespace only around the colon. Using \\s* here lets the
    match run past the end of an empty field and swallow the following line,
    so 'Registrant Organization:' with no value returns the street address.
    """
    for label in labels:
        m = re.search(
            rf"^[ \t]*{re.escape(label)}[ \t]*:[ \t]*(\S.*?)[ \t]*$",
            text, re.IGNORECASE | re.MULTILINE,
        )
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _domain_record(text: str, domain: str) -> "Optional[str]":
    """Slice the response down to the record for this specific domain.

    The macOS whois client concatenates the IANA registry record with the
    registry's own answer. The IANA block has its own 'created', 'organisation'
    and 'country' fields describing the TLD, so parsing the whole response
    reads TLD metadata as if it were the domain's. Returns None when the
    response contains no record for this domain at all.
    """
    m = re.search(
        rf"^[ \t]*(?:Domain Name|domain|Domain)[ \t]*:[ \t]*{re.escape(domain)}[ \t]*$",
        text, re.IGNORECASE | re.MULTILINE,
    )
    return text[m.start():] if m else None


def _from_whois(domain: str) -> WhoisResult:
    """Shell out to the system whois binary and parse its text output."""
    if not shutil.which("whois"):
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none",
            error="no RDAP record and the system 'whois' command is not installed",
        )

    try:
        proc = subprocess.run(
            ["whois", domain],
            capture_output=True, text=True, timeout=WHOIS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.debug("whois timed out for %s", domain)
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none",
            error=f"whois lookup timed out after {WHOIS_TIMEOUT}s",
        )
    except Exception as e:
        log.debug("whois failed for %s: %s", domain, e)
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none", error=f"whois lookup failed: {e}",
        )

    text = proc.stdout or ""
    low = text.lower()

    if not text.strip():
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none",
            error="whois returned an empty response",
        )

    # Only ever parse the block that is actually about this domain. Without a
    # record for it, an explicit "no match" or a bare IANA referral both mean
    # the domain is unregistered.
    record = _domain_record(text, domain)
    if record is None:
        if "iana whois server" in low or any(m in low for m in _NOT_FOUND_MARKERS):
            log.debug("whois has no record for %s, treating as unregistered", domain)
            return WhoisResult(
                domain=domain, found=False, registration_date=None, age_days=None,
                expiry_date=None, registrar=None, registrant_org=None, country=None,
                privacy_redacted=False, source="whois", error=None,
            )
        # Some ccTLDs use a layout we do not recognise. Say so rather than
        # guessing a verdict from fields that may belong to another record.
        log.debug("whois response for %s is in an unrecognised format", domain)
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none",
            error="the whois response did not contain a recognisable record for this domain",
        )

    registered = _parse_date(
        _whois_field(record, "Creation Date", "Created On", "Created", "created",
                     "Domain Registration Date", "Registered On", "Registration Time")
    )
    expires = _parse_date(
        _whois_field(record, "Registry Expiry Date", "Expiry Date", "Expiration Date",
                     "Registrar Registration Expiration Date", "paid-till")
    )
    registrar = _whois_field(record, "Registrar", "Sponsoring Registrar", "registrar")
    org = _whois_field(record, "Registrant Organization", "Registrant Org",
                       "Registrant Name", "org", "OrgName")
    country = _whois_field(record, "Registrant Country", "Country", "country")

    log.debug(
        "whois hit for %s: registered=%s registrar=%s",
        domain, registered.date() if registered else None, registrar,
    )
    return WhoisResult(
        domain=domain,
        found=True,
        registration_date=registered.date().isoformat() if registered else None,
        age_days=_age_days(registered),
        expiry_date=expires.date().isoformat() if expires else None,
        registrar=_clean(registrar),
        registrant_org=_clean(org),
        country=_clean(country),
        privacy_redacted=_is_privacy(org) or _is_privacy(country),
        source="whois",
        error=None,
    )


def lookup(domain: str) -> WhoisResult:
    """Look up one domain. Never raises."""
    normalized = normalize_domain(domain)
    if not normalized or "." not in normalized:
        return WhoisResult(
            domain=domain, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none",
            error=f"{domain!r} is not a usable domain name",
        )

    log.debug("Tool call: whois_lookup(%r) -> %s", domain, normalized)
    try:
        result = _from_rdap(normalized)
        if result is not None:
            return result
        return _from_whois(normalized)
    except Exception as e:
        # Belt and braces: a tool must never take the run down with it.
        log.debug("Lookup blew up for %s: %s", normalized, e)
        return WhoisResult(
            domain=normalized, found=False, registration_date=None, age_days=None,
            expiry_date=None, registrar=None, registrant_org=None, country=None,
            privacy_redacted=False, source="none", error=f"lookup failed: {e}",
        )


def format_result(result: WhoisResult) -> str:
    """Render a lookup as the plain text the LLM sees."""
    if result.error:
        return (
            f"Domain registration lookup for {result.domain} could not be "
            f"completed: {result.error}. Treat this as no information either "
            f"way, not as a warning sign."
        )
    if not result.found:
        return (
            f"Domain {result.domain} has NO registration record. It is not a "
            f"registered domain. If a job posting points to this domain, that "
            f"is a serious warning sign."
        )

    lines = [f"Domain registration record for {result.domain} (via {result.source}):"]
    if result.registration_date:
        age = ""
        if result.age_days is not None:
            years = result.age_days / 365.25
            age = (
                f" ({result.age_days} days ago, about {years:.1f} years)"
                if result.age_days >= 365
                else f" ({result.age_days} days ago)"
            )
        lines.append(f"- Registered: {result.registration_date}{age}")
    else:
        lines.append("- Registered: not disclosed by the registry")
    lines.append(f"- Expires: {result.expiry_date or 'not disclosed'}")
    lines.append(f"- Registrar: {result.registrar or 'not disclosed'}")
    lines.append(f"- Registrant organization: {result.registrant_org or 'not disclosed'}")
    lines.append(f"- Registrant country: {result.country or 'not disclosed'}")
    if result.privacy_redacted or not result.registrant_org:
        lines.append(
            "- Note: registrant details are redacted for privacy. Most "
            "registrars do this by default, so it is normal and NOT by itself "
            "a warning sign."
        )
    return "\n".join(lines)


def whois_lookup(domain: str) -> str:
    """Tool entry point. Returns text for the LLM and never raises."""
    return format_result(lookup(domain))
