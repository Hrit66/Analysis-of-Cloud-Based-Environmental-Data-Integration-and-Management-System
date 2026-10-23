"""Institution/domain allowlist helpers for public signup."""
from __future__ import annotations

import json
from typing import Iterable

from app.config import get_settings


def _split(value: str) -> list[str]:
    return [item.strip().lower().lstrip("@") for item in value.split(",") if item.strip()]


def allowed_domains() -> list[str]:
    return _split(get_settings().ACADEMIC_DOMAIN_ALLOWLIST)


def institutions() -> list[dict]:
    raw = get_settings().INSTITUTIONS_JSON.strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [
                    {"name": str(item["name"]), "domains": [str(d).lower().lstrip("@") for d in item.get("domains", [])]}
                    for item in parsed
                    if isinstance(item, dict) and item.get("name")
                ]
        except (ValueError, TypeError, KeyError):
            pass
    return [
        {"name": "Indian Institute of Technology", "domains": ["iit.ac.in"]},
        {"name": "Indian Institute of Science", "domains": ["iisc.ac.in"]},
        {"name": "University / College", "domains": ["ac.in", "edu", "edu.in"]},
        {"name": "Government agency", "domains": ["gov.in", "nic.in"]},
    ]


def email_domain(email: str) -> str:
    return str(email).rsplit("@", 1)[-1].strip().lower()


def domain_matches(domain: str, suffixes: Iterable[str]) -> bool:
    domain = domain.lower().strip().lstrip("@")
    return any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes)


def is_allowlisted(email: str, domains: Iterable[str]) -> bool:
    return domain_matches(email_domain(email), domains)


def is_allowlisted_academic(email: str) -> bool:
    return is_allowlisted(email, allowed_domains())


def is_government_domain(email: str) -> bool:
    return domain_matches(email_domain(email), _split(get_settings().GOVT_DOMAIN_SUFFIXES))
