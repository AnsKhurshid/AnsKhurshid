"""Deterministic normalisation of job fields."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jobagent.utils.text import norm_key

# ------------------------------------------------------------------ URLs
TRACKING_PARAMS = {
    "trk", "trkinfo", "trackingid", "refid", "ebp", "lipi", "midtoken", "midsig", "trk_info", "originalsubdomain",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "igshid", "yclid", "ref", "referer",
    "referrer", "src", "sourcefrom", "position", "pagenum", "alternatechannel", "otptoken", "recommendedflavor",
    "savedsearchid", "geoid", "keywords", "location", "f_tpr", "f_wt", "start", "distance",
}
TRACKING_PREFIXES = ("utm_", "li_", "hs_", "mkt_", "pk_")
# Identifiers that must survive canonicalisation even though they live in the query string.
KEEP_PARAMS = {"currentjobid", "jobid", "job_id", "jk", "gh_jid", "id", "jid", "req", "reqid", "requisitionid",
               "vjk", "pid", "postingid", "jobreqid", "opening"}


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.startswith("m."):
        host = "www." + host[2:]
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    query = []
    for k, v in parse_qsl(p.query, keep_blank_values=False):
        kl = k.lower()
        if kl in KEEP_PARAMS or not (kl in TRACKING_PARAMS or kl.startswith(TRACKING_PREFIXES)):
            query.append((k, v))
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/") + ("/" if "linkedin.com" in host else "")
    return urlunparse(("https", host, path, "", urlencode(sorted(query)), ""))


# ------------------------------------------------------------------ titles
SENIORITY_PATTERNS = [
    ("intern", r"\b(intern|internship|trainee)\b"),
    ("junior", r"\b(junior|jr\.?|entry[- ]level|associate|graduate|fresh(er)?)\b"),
    ("lead", r"\b(lead|staff|tech lead|team lead)\b"),
    ("principal", r"\b(principal|architect|head of|director|vp|vice president)\b"),
    ("manager", r"\b(manager|mgr)\b"),
    ("senior", r"\b(senior|sr\.?|iii|level 3)\b"),
    ("mid", r"\b(mid[- ]level|intermediate|ii|level 2)\b"),
]

ROLE_CATEGORIES = [
    # (category, regex over normalised title, alignment weight 0..1 used by matching)
    ("aws_data_engineer", r"\b(aws|cloud) data engineer"),
    ("analytics_engineer", r"\banalytics engineer"),
    ("data_integration_engineer", r"\b(data integration|integration) (engineer|developer|specialist)"),
    ("etl_developer", r"\b(etl|elt|ssis|informatica|talend)\b.*\b(developer|engineer|specialist|consultant)"),
    ("data_engineer", r"\b(big data|data platform|data pipeline|data)\s+(engineer|engineering|developer)\b"),
    ("data_engineer", r"\bdata ops\b|\bdataops\b"),
    ("bi_engineer", r"\b(bi|business intelligence|power bi|tableau|reporting)\s+(engineer|developer|consultant)"),
    ("database_developer", r"\b(database|sql|db|pl ?sql)\s+(developer|engineer|programmer)"),
    ("database_administrator", r"\b(dba|database administrator)\b"),
    ("ml_engineer", r"\b(ml|machine learning|mlops|ai)\s+engineer"),
    ("data_scientist", r"\bdata scien"),
    ("data_analyst", r"\b(data|business|bi|reporting|marketing|financial|product)\s+analyst"),
    ("data_architect", r"\bdata architect"),
    ("software_engineer", r"\b(software|backend|back end|full ?stack|python|java|web)\s+(engineer|developer)"),
]


def normalize_title(title: str | None) -> str:
    t = (title or "").strip()
    t = re.sub(r"\((?:[^)]*(?:remote|hybrid|on-?site|onsite|urgent|immediate|contract|full[- ]time)[^)]*)\)", "", t, flags=re.I)
    t = re.sub(r"\s+[-–|@]\s+(?:remote|hybrid|on-?site|lahore|karachi|islamabad|pakistan|urgent).*$", "", t, flags=re.I)
    t = re.sub(r"\b(urgent(ly)?|hiring|immediate joiner|required|needed)\b", "", t, flags=re.I)
    return norm_key(t)


def seniority_of(title: str | None) -> str | None:
    t = (title or "").lower()
    for level, pat in SENIORITY_PATTERNS:
        if re.search(pat, t):
            return level
    return None


def role_category(title: str | None) -> str:
    t = normalize_title(title)
    if re.search(r"\bpython\b", t) and re.search(r"\bdata engineer", t):
        return "python_data_engineer"
    if re.search(r"\bsql\b", t) and re.search(r"\bdata engineer", t):
        return "sql_data_engineer"
    for cat, pat in ROLE_CATEGORIES:
        if re.search(pat, t):
            return cat
    return "other"


# ------------------------------------------------------------------ companies
COMPANY_SUFFIXES = r"\b(pvt|private|ltd|limited|llc|inc|incorporated|corp|corporation|co|gmbh|plc|smc|pte|llp|sa|bv)\b\.?"


def normalize_company(name: str | None) -> str:
    n = (name or "").lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(COMPANY_SUFFIXES, " ", n)
    n = re.sub(r"\bpakistan\b", " ", n)
    return norm_key(n)


# ------------------------------------------------------------------ locations
PK_CITIES = {
    "lahore": "Lahore", "lhr": "Lahore", "karachi": "Karachi", "khi": "Karachi", "islamabad": "Islamabad",
    "isb": "Islamabad", "rawalpindi": "Rawalpindi", "pindi": "Rawalpindi", "faisalabad": "Faisalabad",
    "multan": "Multan", "peshawar": "Peshawar", "quetta": "Quetta", "sialkot": "Sialkot",
    "gujranwala": "Gujranwala", "hyderabad, sindh": "Hyderabad", "abbottabad": "Abbottabad",
}
PK_REGIONS = ("punjab", "sindh", "khyber pakhtunkhwa", "kpk", "balochistan", "islamabad capital territory")
COUNTRIES = {
    "pakistan": "Pakistan", "united states": "United States", "usa": "United States", "united kingdom": "United Kingdom",
    "uk": "United Kingdom", "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates",
    "saudi arabia": "Saudi Arabia", "ksa": "Saudi Arabia", "qatar": "Qatar", "germany": "Germany",
    "netherlands": "Netherlands", "canada": "Canada", "australia": "Australia", "india": "India",
    "ireland": "Ireland", "poland": "Poland", "spain": "Spain", "singapore": "Singapore", "malaysia": "Malaysia",
    "european union": "European Union", "emea": "EMEA", "europe": "Europe", "worldwide": "Worldwide",
    "anywhere": "Worldwide", "global": "Worldwide",
}


def parse_location(location: str | None) -> tuple[str | None, str | None]:
    """Return (city, country) using explicit tokens only."""
    if not location:
        return None, None
    low = location.lower()
    city = next((v for k, v in PK_CITIES.items() if re.search(rf"\b{re.escape(k)}\b", low)), None)
    country = None
    if city or any(r in low for r in PK_REGIONS):
        country = "Pakistan"
    for k, v in COUNTRIES.items():
        if re.search(rf"\b{re.escape(k)}\b", low):
            country = country or v
            break
    if city is None and "," in location:
        first = location.split(",")[0].strip()
        if first and first.lower() not in COUNTRIES and len(first) < 40:
            city = first.title()
    return city, country


# ------------------------------------------------------------------ arrangement / employment type
def detect_work_arrangement(explicit: str | None, title: str | None, location: str | None,
                            description: str | None) -> str:
    for text in (explicit, title, location):
        t = (text or "").lower()
        if "hybrid" in t:
            return "hybrid"
        if re.search(r"\bremote\b|work from home|\bwfh\b|telecommute", t):
            return "remote"
        if re.search(r"on-?site|onsite|in[- ]office|office[- ]based", t):
            return "on-site"
    d = (description or "").lower()
    if re.search(r"\bhybrid\b", d):
        return "hybrid"
    if re.search(r"\b(fully|100%) remote\b|\bremote[- ](first|role|position|job|opportunity)\b|work from home|\bwfh\b", d):
        return "remote"
    if re.search(r"\b(on-?site|onsite|in[- ]office|work from (the )?office|office[- ]based)\b", d):
        return "on-site"
    return "unknown"


def normalize_employment_type(value: str | None, description: str | None = None) -> str | None:
    t = (value or "").lower().replace("_", " ")
    for text in (t, (description or "").lower()[:3000] if not t else ""):
        if re.search(r"\bintern", text):
            return "internship"
        if re.search(r"contract|freelance|consultant|temporary|temp\b", text):
            return "contract"
        if re.search(r"part[- ]time", text):
            return "part-time"
        if re.search(r"full[- ]time|permanent", text):
            return "full-time"
    return None


# ------------------------------------------------------------------ salary
SALARY_RE = re.compile(
    r"(?P<cur>PKR|Rs\.?|USD|\$|EUR|€|GBP|£|AED)\s*(?P<min>\d[\d,.]*\s*[kK]?)\s*(?:-|–|to)\s*(?P<cur2>PKR|Rs\.?|USD|\$|EUR|€|GBP|£|AED)?\s*(?P<max>\d[\d,.]*\s*[kK]?)"
    r"(?:\s*(?:per|/|a)\s*(?P<period>month|year|annum|hour|yr|mo))?", re.I)
CURRENCY = {"pkr": "PKR", "rs": "PKR", "rs.": "PKR", "usd": "USD", "$": "USD", "eur": "EUR", "€": "EUR",
            "gbp": "GBP", "£": "GBP", "aed": "AED"}


def _num(s: str) -> float | None:
    s = s.strip().replace(",", "")
    mult = 1000 if s.lower().endswith("k") else 1
    try:
        return float(s.rstrip("kK").strip()) * mult
    except ValueError:
        return None


def parse_salary(text: str | None) -> tuple[float | None, float | None, str | None, str | None]:
    m = SALARY_RE.search(text or "")
    if not m:
        return None, None, None, None
    period = (m.group("period") or "").lower() or None
    period = {"annum": "year", "yr": "year", "mo": "month"}.get(period, period)
    return _num(m.group("min")), _num(m.group("max")), CURRENCY.get(m.group("cur").lower()), period
