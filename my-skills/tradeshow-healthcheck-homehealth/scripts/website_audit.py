"""
Website Audit - Trade Show Health Check (Home Health Edition, Hard Mode)

Fetches a homepage and runs 10 hard checks designed to surface real
issues the home health prospect doesn't know about. These are
intentionally strict so most agency sites do not score an A.

Home health is referral-source-driven (hospitals, SNFs, physicians,
discharge planners) AND family-driven (especially after hospital
discharge or new diagnosis). Both audiences look at the website. The
checks reflect both:

Checks:
  1. Real photos (no stock photo CDNs / generic alt text)
  2. PageSpeed mobile score >= 50 (Google PageSpeed Insights API)
  3. About/team page exists with real staff signals
  4. Intake form / scheduling widget (not just a phone number)
  5. LocalBusiness or HomeHealthAgency schema markup
  6. Google reviews widget embedded on the site
  7. Medicare-certified mention (homepage or About/Services page)
  8. Services list (skilled nursing, PT, OT, ST, MSW, HHA, etc.)
  9. Referral source page (dedicated page or form for hospitals, SNFs,
     physicians, case managers)
 10. CMS Star Rating displayed (from Care Compare)

Detects platform when possible (HealthcareSuccess, Stratus Interactive,
Hearst Health, BlueOrange Compass, plus generic WordPress/Squarespace/
Wix). Platform is NOT graded.

Grade: A (10/10), B (7-9), C (4-6), D (1-3), F (0)

Usage:
    python website_audit.py --url https://example.com
"""

import argparse
import json
import os
import re
import threading
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

import site_reader   # the shared site reader, pinned byte-identical across the five tools (2026-10-29)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ----------------------------- helpers -----------------------------


def get_google_api_key():
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "[System.Environment]::GetEnvironmentVariable('GOOGLE_API_KEY', 'User')"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""



# ---- "Couldn't check", never "No" from a page nobody read (Welton, 2026-10-20) ----------------------
# A check used to answer No whenever a page it needed could not be read (blocked, rate-limited, server
# error, no connection), and when a site refused the address probes. Now every fetch and probe made
# while a check runs notes the pages it could not read, and measured() turns that check's No into None
# ("Couldn't check"). A Yes stands (it was seen); a page that is not there (404/410) is still a No.

# ---- A homepage that loads with almost nothing readable is built in the browser (Welton, 2026-10-20) ----
# Measured on 200 sites from the saved runs (ops/receipts/20261020T171217_script-built-homepages-measured.txt):
# 19 of 81 funeral home homepages came back with 18 to 65 readable characters (one platform: Tribute /
# FrontRunner / FuneralTech) and 1,000 to 8,000 once a browser ran their scripts; the thinnest real page
# had 415. The booth printed 2 to 4 "No"s on each, 13 of them provably false ("Pre-need form: No" beside
# a pre-planning link). Under MIN_READABLE_CHARS the website reads "Couldn't check", no grade.
MIN_READABLE_CHARS = 200
SCRIPT_BUILT_REASON = "Couldn't check (site loads its content in the browser)"


def readable_chars(html):
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return len(" ".join(t.split()))

_reads = threading.local()


def _note_unread(url, why):
    unread = getattr(_reads, "unread", None)
    if unread is not None:
        unread.append((url, why))


def measured(check, *args):
    """Run one check. Its No becomes None when a page it needed could not be read."""
    _reads.unread = []
    try:
        result = check(*args)
    finally:
        unread, _reads.unread = _reads.unread, None
    if not unread:
        return result
    if result is False or result is None:
        return None
    if isinstance(result, dict) and not result.get("pass"):
        return dict(result, **{"pass": None})
    if isinstance(result, tuple) and result and not result[0]:
        return (None,) + tuple(result[1:])
    return result


def fetch_page(url, timeout=15):
    if not url:
        return None, None, "no url"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code in (401, 403, 407, 429) or r.status_code >= 500:
            _note_unread(url, "HTTP %s" % r.status_code)
        return r.text, r.status_code, r.url
    except Exception as e:
        _note_unread(url, str(e)[:80])
        return None, None, str(e)


def base_origin(url):
    """Return scheme://host of a URL."""
    try:
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def find_internal_link(html, base_url, url_keywords):
    """Find first <a href> whose path contains any of the keywords."""
    if not html or not base_url:
        return None
    # href="...", href='...' or href=... are all links (Welton 2026-10-21: a site whose links use single
    # quotes read "No" for a team page, blog, pre-need form, obituary page, gallery or livestream it has).
    pattern = re.compile(r"""<a[^>]+href\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        href_low = href.lower()
        for kw in url_keywords:
            if kw in href_low:
                if href.startswith("http"):
                    url = href
                elif href.startswith("//"):
                    url = "https:" + href
                elif href.startswith("/"):
                    url = base_url + href
                else:
                    url = urllib.parse.urljoin(base_url + "/", href)
                if site_reader.same_site(url, base_url):
                    return url
                # Another site's page is not theirs (Welton 2026-10-29): not read, and a No that needed it is
                # "couldn't check". Look at the next link.
                _note_unread(url, "another site")
                break
    return None


def find_internal_link_by_path(html, base_url, paths):
    """Try a fixed list of candidate paths against the base URL even if no
    matching href appeared on the homepage."""
    if not base_url:
        return None
    for p in paths:
        url = base_url.rstrip("/") + p
        try:
            r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
            if r.status_code and 200 <= r.status_code < 300:
                return r.url
            if r.status_code not in (404, 410):
                _note_unread(url, "HEAD %s" % r.status_code)   # the site would not say; not "no page"
        except Exception as e:
            _note_unread(url, str(e)[:80])
            continue
    return None


def fetch_aux_pages(home_html, base_url, paths, timeout=8):
    """Crawl one level deep on the given paths. For each path:
      1. Try to find a matching href on the homepage (loose substring match).
      2. If not found, try the path directly via HEAD probe on the base URL.
    Returns list of (final_url, html) tuples for pages that fetched 2xx.
    Deduped by final URL.

    This is the helper that lets the Medicare-cert / services / referral
    checks see the linked sub-pages even when the homepage doesn't surface
    a clean href to them. Most HH agencies put 'Medicare-certified' or
    their service catalog on /services or /about-us, not above the fold."""
    if not base_url:
        return []
    pages = []
    seen = set()
    for path in paths:
        url = (
            find_internal_link(home_html or "", base_url, [path])
            or find_internal_link_by_path(home_html or "", base_url, [path])
        )
        if not url:
            continue
        # Normalize: strip trailing slash, lowercase host for dedup
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        page_html, status, final_url = fetch_page(url, timeout=timeout)
        if page_html and status and 200 <= status < 300:
            pages.append((final_url or url, page_html))
    return pages


# ----------------------------- 1. Real photos vs stock -----------------------------

STOCK_INDICATORS = [
    "shutterstock", "istockphoto", "gettyimages", "stock.adobe",
    "depositphotos", "dreamstime", "123rf.com", "alamy.com", "bigstock",
    "fotolia", "unsplash.com", "pexels.com", "pixabay.com",
    "stocksnap.io", "freepik.com", "canva.com/photos",
    "stock-photo", "stock_photo", "/stock/", "shutterstock_",
    "istock_", "gettyimages-",
]

# Home-health-vertical generic alt patterns (caregiver+patient,
# stethoscope, pill bottles, etc).
GENERIC_ALT_PATTERNS = [
    r'alt="[^"]*nurse (?:and|with) (?:patient|elderly|senior)',
    r'alt="[^"]*caregiver (?:and|with) (?:patient|client|senior|elderly)',
    r'alt="[^"]*holding hands with (?:elderly|senior|patient)',
    r'alt="[^"]*stethoscope',
    r'alt="[^"]*pill\s*bottles?',
    r'alt="[^"]*medication',
    r'alt="[^"]*medical\s+chart',
    r'alt="[^"]*senior\s+couple',
    r'alt="[^"]*elderly\s+(?:woman|man|couple|person|lady|gentleman)',
    r'alt="[^"]*happy\s+senior',
    r'alt="[^"]*smiling\s+elderly',
]


def check_real_photos(html):
    """Return True if NO stock photo indicators found."""
    html_lower = html.lower()
    for hint in STOCK_INDICATORS:
        if hint in html_lower:
            return False
    generic_alt_hits = 0
    for pat in GENERIC_ALT_PATTERNS:
        if re.search(pat, html_lower):
            generic_alt_hits += 1
            if generic_alt_hits >= 2:
                return False
    return True


# ----------------------------- 2. PageSpeed Insights -----------------------------


PSI_RUNS = 5          # Google's speed test runs per scan, all at once
PSI_MIN_RUNS = 3      # fewer back than this is couldn't check


def check_pagespeed(url, api_key, timeout=90):
    """Google's mobile speed test, run PSI_RUNS times at once (Welton 2026-10-22).

    One run is not a measurement. Six fresh runs of one page within a minute scored 30 to 57 (Forest Lawn), 41 to 55
    (Veritas) and 40 to 62 (Haven); the sheets had printed one run each (26, 37, 52), and Veritas's "slow page" bullet
    fired on a page Google's own site scored 54. Each run gets its own address (a harmless rrm_psi tag): Google hands
    back its cached answer for an address it tested moments ago, so five runs of one address are one run.

    Returns the runs' low and high. score is the HIGH run and pass is high >= 50, so nothing calls a page slow unless
    every run said so: the owner can run the test himself, and one good run of his disproves a slow claim built on a
    bad run of ours. Fewer than PSI_MIN_RUNS runs back is couldn't check (score None), never a verdict.
    """
    if not api_key:
        sys.stderr.write("[pagespeed] no GOOGLE_API_KEY available\n")
        return {"score": None, "pass": None, "error": "no api key"}
    if not url:
        return {"score": None, "pass": None, "error": "no url"}

    def one(n):
        base, hash_, frag = url.partition("#")
        tagged = base + ("&" if "?" in base else "?") + "rrm_psi=%d" % n + hash_ + frag
        try:
            r = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", timeout=timeout,
                             params={"url": tagged, "strategy": "mobile", "category": "performance", "key": api_key})
            if r.status_code != 200:
                return None, "HTTP %s: %s" % (r.status_code, r.text[:160])
            score = r.json().get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
            return (None, "no score in response") if score is None else (round(score * 100), None)
        except Exception as e:
            return None, str(e)[:200]

    with ThreadPoolExecutor(max_workers=PSI_RUNS) as ex:
        runs = list(ex.map(one, range(1, PSI_RUNS + 1)))
    scores = sorted(s for s, _ in runs if s is not None)
    errors = [e for _, e in runs if e]
    for e in errors:
        sys.stderr.write("[pagespeed] a run failed for %s: %s\n" % (url, e))
    if len(scores) < PSI_MIN_RUNS:
        return {"score": None, "pass": None, "scores": scores,
                "error": "only %d of %d speed tests came back%s" % (len(scores), PSI_RUNS, (": " + errors[0]) if errors else "")}
    return {"score": scores[-1], "low": scores[0], "high": scores[-1], "scores": scores, "pass": scores[-1] >= 50}


# ----------------------------- 3. About/Team page -----------------------------

TEAM_URL_KEYWORDS = [
    "/team", "/our-team", "/our_team", "/staff", "/our-staff",
    "/meet-the-team", "/meet-our-team", "/leadership", "/our-people",
    "/clinicians", "/nurses", "/our-nurses",
]
ABOUT_URL_KEYWORDS = ["/about", "/who-we-are", "/our-story", "/our-mission"]
ROLE_KEYWORDS = [
    "founder", "co-founder", "owner", "co-owner", "director",
    "administrator", "ceo", "president", "vice president",
    "manager", "coordinator", "registered nurse", "rn,",
    "rn ", "lpn", "lvn", "physical therapist", "occupational therapist",
    "speech therapist", "speech-language pathologist",
    "medical social worker", "msw", "case manager",
    "director of patient services", "dps",
    "clinical manager", "director of nursing", "don",
]


def check_about_team(home_html, base_url):
    """Pass if a dedicated team page exists OR /about contains 3+ role hits."""
    team_url = find_internal_link(home_html, base_url, TEAM_URL_KEYWORDS)
    if team_url:
        page_html, status, _ = fetch_page(team_url, timeout=10)
        if page_html and status and 200 <= status < 300:
            text = re.sub(r"<[^>]+>", " ", page_html).lower()
            role_hits = sum(1 for kw in ROLE_KEYWORDS if kw in text)
            if role_hits >= 1:
                return True

    about_url = find_internal_link(home_html, base_url, ABOUT_URL_KEYWORDS)
    if about_url:
        page_html, status, _ = fetch_page(about_url, timeout=10)
        if page_html and status and 200 <= status < 300:
            text = re.sub(r"<[^>]+>", " ", page_html).lower()
            role_hits = sum(1 for kw in ROLE_KEYWORDS if kw in text)
            if role_hits >= 3:
                return True
    return False


# ----------------------------- 4. Intake form / scheduling -----------------------------

SCHEDULING_HINTS = [
    # A booking or form service counts only when it is EMBEDDED in this page (Welton 2026-10-22: a Contact link is not
    # a form): an iframe from it, or the service's own inline-widget element or form-creating call. A plain link to it
    # is a link. Form plugins (Gravity Forms, WPForms, Contact Form 7, Ninja, Fluent) are not listed: a form they draw
    # is a real <form> on the page, counted below, and their files load on every page of a site whether or not this
    # page has a form.
    "calendly.com", "acuityscheduling", "squareup.com/appointments", "jotform.com", "typeform.com", "formstack",
    "hsforms", "hubspot.com/forms",
]
EMBED_MARKERS = ("calendly-inline-widget", "hbspt.forms.create", "data-tf-widget", "data-tf-live")


def check_intake_form(html):
    """Pass only on a form ON THIS PAGE: a <form> with 3+ visible fields (a popup form built into the page counts), or
    a scheduling / form service embedded here. One identical function in the three booth tools that carry it
    (test_booth_form_check.py)."""
    for m in re.finditer(r"<iframe\b[^>]*\bsrc=[\"']([^\"']+)", html, re.IGNORECASE):
        if any(h in m.group(1).lower() for h in SCHEDULING_HINTS):
            return True
    html_lower = html.lower()
    if any(mk in html_lower for mk in EMBED_MARKERS):
        return True
    forms = re.findall(r"<form\b[^>]*>(.*?)</form>", html, re.IGNORECASE | re.DOTALL)
    for form in forms:
        form_low = form.lower()
        if 'role="search"' in form_low or 'type="search"' in form_low:
            continue
        if 'class="searchform' in form_low or 'id="searchform' in form_low:
            continue
        inputs = re.findall(r"<(input|textarea|select)\b[^>]*>", form, re.IGNORECASE)
        hidden = len(re.findall(r'<input[^>]+type=["\']hidden["\']', form, re.IGNORECASE))
        submit = len(re.findall(r'<input[^>]+type=["\']submit["\']', form, re.IGNORECASE))
        real_inputs = len(inputs) - hidden - submit
        if real_inputs >= 3:
            return True
    return False


# ----------------------------- 5. LocalBusiness schema -----------------------------

SCHEMA_TARGET_TYPES = [
    "LocalBusiness", "HomeHealthAgency", "MedicalBusiness",
    "MedicalOrganization", "MedicalClinic", "Physician",
    "HealthAndBeautyBusiness", "ProfessionalService", "EmergencyService",
]


def check_local_business_schema(html):
    """Look for application/ld+json blocks containing LocalBusiness / HomeHealthAgency."""
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        block = m.group(1)
        for t in SCHEMA_TARGET_TYPES:
            if f'"{t}"' in block or f"'{t}'" in block:
                return True
    return False


# ----------------------------- 6. Google reviews widget -----------------------------

REVIEWS_WIDGET_HINTS = [
    "elfsight.com", "elfsight-app",
    "trustindex.io", "trustindex",
    "sociablekit",
    "reviewsonmywebsite.com",
    "embedreviews", "embedsocial",
    "tagembed.com", "widget-tagembed",
    "shapo.io",
    "famewall",
    "google-reviews-widget", "googlereviewswidget",
    "g-reviews-widget",
    "widget.reviewsforce",
    "rwgmaps",
    "trustpulse",
    "reputationmanager", "reviewbuilder",
]


def check_google_reviews_widget(html):
    html_lower = html.lower()
    for h in REVIEWS_WIDGET_HINTS:
        if h in html_lower:
            return True
    return False


# ----------------------------- 7. Medicare-certified mention -----------------------------

# Most Medicare-certified HH agencies use one of these phrases somewhere
# on their site (homepage, About, Services, How We Work, Credentials,
# or Accreditation pages). Including accreditor names like CHAP, ACHC,
# and the Joint Commission since many agencies advertise the accreditor
# rather than spelling out "Medicare-certified".
MEDICARE_CERT_PATTERNS = [
    r"medicare[\s\-]+certified",
    r"medicare\s+certification",
    r"certified\s+by\s+medicare",
    r"medicare[\s\-]+approved",
    r"medicare\s+provider",
    r"cms[\s\-]+certified",
    r"certified\s+by\s+(?:cms|medicare)",
    # Accreditation bodies whose certification is functionally equivalent
    r"chap[\s\-]+accredit\w*",
    r"chap\s+accreditation",
    r"community\s+health\s+accreditation\s+(?:program|partner)",
    r"achc[\s\-]+accredit\w*",
    r"achc\s+accreditation",
    r"accreditation\s+commission\s+for\s+health\s+care",
    r"joint\s+commission[\s\-]+accredit\w*",
    r"joint\s+commission\s+accreditation",
    r"accredited\s+by\s+(?:chap|achc|the\s+joint\s+commission)",
]
MEDICARE_AUX_PATHS = [
    "/medicare", "/certifications", "/certification", "/our-credentials",
    "/credentials", "/accreditation", "/accreditations",
    "/about", "/about-us", "/our-story", "/who-we-are",
    "/services", "/our-services", "/what-we-do",
    "/how-we-work", "/why-choose-us", "/why-us", "/quality",
    "/quality-of-care", "/our-difference",
]


def check_medicare_certified(home_html, base_url):
    """Pass if 'Medicare-certified' (or any of the equivalent accreditation
    phrases) appears on the homepage OR on any of the aux pages we crawl
    one level deep. Discharge planners and savvy families look for this
    signal explicitly, but agencies rarely place it above the fold."""
    pages_text = [home_html or ""]
    for _, page_html in fetch_aux_pages(home_html or "", base_url, MEDICARE_AUX_PATHS):
        pages_text.append(page_html)

    blob = " ".join(pages_text).lower()
    blob = re.sub(r"<[^>]+>", " ", blob)
    blob = re.sub(r"\s+", " ", blob)
    for pat in MEDICARE_CERT_PATTERNS:
        if re.search(pat, blob):
            return True
    return False


# ----------------------------- 8. Services list -----------------------------

# Cover the canonical Medicare home health service set. Strong sites
# enumerate several; vague sites mention none.
HH_SERVICES = [
    "skilled nursing", "registered nurse", "rn services", "lpn services",
    "physical therapy", "physical therapist",
    "occupational therapy", "occupational therapist",
    "speech therapy", "speech-language pathology", "speech-language",
    "medical social work", "medical social worker", "msw",
    "home health aide", "home health aides", "hha",
    "wound care", "ostomy care",
    "iv therapy", "infusion therapy",
    "diabetic care", "diabetes management",
    "post-surgical", "post-surgery", "post-op", "post-discharge",
    "telehealth", "remote monitoring",
    "pain management", "fall prevention",
    "chronic disease management", "chronic care",
    "cardiac care", "ckd care", "ostomy",
]

SERVICES_AUX_PATHS = [
    "/services", "/our-services", "/what-we-do", "/care", "/care-services",
    "/programs", "/program", "/specialties", "/specialty",
    "/skilled-nursing", "/therapy", "/therapies",
    "/conditions", "/conditions-we-treat",
    # Many HH sites list services on the home / about pages too
    "/about", "/about-us",
]


def detect_services(html):
    """Return list of services found in the HTML."""
    if not html:
        return []
    text = re.sub(r"<[^>]+>", " ", html).lower()
    text = re.sub(r"\s+", " ", text)
    found = []
    for term in HH_SERVICES:
        if term in text and term not in found:
            found.append(term)
    return found


def check_services_list(home_html, base_url):
    """Pass if 4+ distinct service categories detected across homepage AND
    any service-related sub-pages we crawl one level deep. Many HH sites
    have a /services landing page with the actual service list while the
    homepage only mentions one or two."""
    found = set(detect_services(home_html))

    for _, page_html in fetch_aux_pages(home_html or "", base_url, SERVICES_AUX_PATHS, timeout=10):
        found.update(detect_services(page_html))

    # Bucket related terms so we count distinct disciplines, not synonyms
    buckets = {
        "skilled_nursing": {"skilled nursing", "registered nurse", "rn services", "lpn services"},
        "pt": {"physical therapy", "physical therapist"},
        "ot": {"occupational therapy", "occupational therapist"},
        "st": {"speech therapy", "speech-language pathology", "speech-language"},
        "msw": {"medical social work", "medical social worker", "msw"},
        "hha": {"home health aide", "home health aides", "hha"},
        "wound": {"wound care", "ostomy care", "ostomy"},
        "iv": {"iv therapy", "infusion therapy"},
        "chronic": {"diabetic care", "diabetes management",
                     "chronic disease management", "chronic care",
                     "cardiac care", "ckd care", "pain management"},
        "post_acute": {"post-surgical", "post-surgery", "post-op",
                        "post-discharge", "fall prevention"},
        "tele": {"telehealth", "remote monitoring"},
    }

    distinct_buckets = sum(1 for terms in buckets.values() if found & terms)
    return distinct_buckets >= 4, sorted(found)


# ----------------------------- 9. Referral source page -----------------------------

REFERRAL_AUX_PATHS = [
    "/refer", "/referral", "/referrals", "/refer-a-patient",
    "/refer-patient", "/physician-referral", "/physicians",
    "/for-physicians", "/for-providers", "/providers",
    "/discharge-planners", "/case-managers", "/case-management",
    "/healthcare-professionals", "/healthcare-pros", "/professionals",
    "/clinicians", "/clinician",
    "/partners", "/hospital-partners", "/our-partners",
]
REFERRAL_BODY_HINTS = [
    "refer a patient", "patient referral", "physician referral",
    "make a referral", "submit a referral",
    "discharge planner", "discharge planners",
    "case manager", "case managers",
    "for hospitals", "for physicians", "for providers",
    "for healthcare professionals", "for clinicians",
    "hospital partners", "snf partners", "skilled nursing facility",
]


def check_referral_page(home_html, base_url):
    """Pass if there's a dedicated referral page reachable via homepage
    href OR direct path probe, OR if referral language is prominent
    across the homepage and any aux pages we crawl. Most HH revenue
    comes from referral sources, not family self-referrals; missing
    this is a real revenue gap."""
    aux_pages = fetch_aux_pages(home_html or "", base_url, REFERRAL_AUX_PATHS, timeout=10)
    if aux_pages:
        # Any referral-named page that fetches 2xx is a pass.
        return True

    # Fallback: prominent referral copy on the homepage (>=2 hints)
    if home_html:
        text = re.sub(r"<[^>]+>", " ", home_html).lower()
        text = re.sub(r"\s+", " ", text)
        hits = sum(1 for h in REFERRAL_BODY_HINTS if h in text)
        if hits >= 2:
            return True
    return False


# ----------------------------- 10. CMS Star Rating displayed -----------------------------

STAR_RATING_PATTERNS = [
    r"\b([1-5](?:\.\d)?)\s*star[-\s]+(?:rating|rated)\b",
    r"\bcms\s+star\s+rating\s*[:=]?\s*([1-5](?:\.\d)?)\b",
    r"\bquality\s+of\s+(?:patient\s+)?care\s+star\s+rating\s*[:=]?\s*([1-5](?:\.\d)?)",
    r"\bcare\s+compare\s+(?:rating|stars?)\s*[:=]?\s*([1-5](?:\.\d)?)",
]
STAR_MENTION_PATTERNS = [
    r"\bcms\s+star\s+rating\b",
    r"\bcare\s+compare\b",
    r"\bquality\s+of\s+(?:patient\s+)?care\s+star\s+rating\b",
    r"\bmedicare\s+star\s+rating\b",
    r"\bfive[-\s]star\s+rated\b",
    r"\b5[-\s]star\s+rated\b",
]


def check_cms_star_rating(html):
    """Returns (passed, value_or_None). Pass if the page mentions a CMS /
    Care Compare star rating. Also captures the numeric value if shown.

    What this measures is whether a star rating is SHOWN ON THE HOMEPAGE, nothing about the agency's
    actual CMS rating (nothing here asks CMS), so the sheet says "Star rating on homepage" (Welton
    2026-10-21). No homepage read: None, couldn't check, never a No."""
    if not html:
        return None, None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    text_l = text.lower()
    # Try to extract a numeric rating
    for pat in STAR_RATING_PATTERNS:
        m = re.search(pat, text_l)
        if m:
            return True, m.group(1)
    # Generic mention without numeric value
    for pat in STAR_MENTION_PATTERNS:
        if re.search(pat, text_l):
            return True, None
    return False, None


# ----------------------------- platform detection -----------------------------

# Home health website platforms. Detected via fingerprints in HTML.
PLATFORM_FINGERPRINTS = [
    ("HealthcareSuccess", [
        "healthcaresuccess.com", "healthcaresuccess-cdn",
    ]),
    ("Stratus Interactive", [
        "stratusinteractive.com", "stratus-interactive",
    ]),
    ("Hearst Health", [
        "hearsthealth.com", "hearst-health",
    ]),
    ("BlueOrange Compass", [
        "blueorangecompass.com", "blueorange-compass",
    ]),
    ("Squarespace", [
        "squarespace.com", "static.squarespace.com",
    ]),
    ("WordPress", [
        "wp-content/", "wp-includes/", "/wp-json/",
    ]),
    ("Wix", [
        "wix.com", "wixstatic.com",
    ]),
    ("HubSpot CMS", [
        "hubspot.net", "hs-scripts.com",
    ]),
]


def detect_platform(html):
    """Return platform name string, or 'Unknown' if no match."""
    if not html:
        return "Unknown"
    html_lower = html.lower()
    for name, fingerprints in PLATFORM_FINGERPRINTS:
        for fp in fingerprints:
            if fp in html_lower:
                return name
    return "Unknown"


# ----------------------------- grading -----------------------------


def grade_website(checks):
    """A=10/10, B=7-9, C=4-6, D=1-3, F=0. None values are excluded and the
    threshold is scaled proportionally."""
    real = [(k, v) for k, v in checks.items() if v is not None]
    if not real or len(real) * 2 < len(checks):
        return None   # too little measured to grade (most checks could not read their page)
    passed = sum(1 for _, v in real if v)
    total = len(real)
    scaled = round(passed * 10 / total)
    if scaled >= 10:
        return "A"
    if scaled >= 7:
        return "B"
    if scaled >= 4:
        return "C"
    if scaled >= 1:
        return "D"
    return "F"


# ----------------------------- main entry -----------------------------


def audit(url):
    if not url:
        return {
            "url": "",
            "error": "no url provided",
            "checks": {},
            "grade": "F",
        }

    html, status, final_url = fetch_page(url)
    if html is None:
        return {
            "url": url,
            "error": f"fetch failed: {final_url}",
            "checks": {},
            "grade": "F",
        }
    moved = site_reader.landed_elsewhere(url, final_url)
    if moved:
        # Before the error check: an address that lands on another site, even one that answers with an error, is
    # the finding. The address we have lands on another site (Welton 2026-10-29): another site is not theirs to audit, and
        # where it went is the finding ("is your website still at that address?").
        return {
            "url": final_url,
            "status": status,
            "error": "the address goes to another site",
            "checks": {},
            "grade": None,
            "unverified": True,
            "unverified_reason": site_reader.MOVED % (site_reader.site_name(url), moved),
            "moved_from": site_reader.site_name(url),
            "moved_to": moved,
        }

    if status and status >= 400:
        return {
            "url": url,
            "error": f"HTTP {status}",
            "checks": {},
            "grade": "F",
        }

    if readable_chars(html) < MIN_READABLE_CHARS:
        return {
            "url": final_url,
            "status": status,
            "error": "site loads its content in the browser",
            "checks": {},
            "grade": None,
            "unverified": True,
            "unverified_reason": SCRIPT_BUILT_REASON,
        }

    base_url = base_origin(final_url)
    api_key = get_google_api_key()

    with ThreadPoolExecutor(max_workers=6) as ex:
        psi_future = ex.submit(check_pagespeed, final_url, api_key)
        team_future = ex.submit(measured, check_about_team, html, base_url)
        medicare_future = ex.submit(measured, check_medicare_certified, html, base_url)
        services_future = ex.submit(measured, check_services_list, html, base_url)
        referral_future = ex.submit(measured, check_referral_page, html, base_url)

        psi = psi_future.result()
        about_team_pass = team_future.result()
        medicare_pass = medicare_future.result()
        services_pass, services_offered = services_future.result()
        referral_pass = referral_future.result()

    star_pass, star_value = check_cms_star_rating(html)

    checks = {
        "real_photos": check_real_photos(html),
        "pagespeed_mobile": psi.get("pass"),
        "about_team_page": about_team_pass,
        "intake_form": check_intake_form(html),
        "localbusiness_schema": check_local_business_schema(html),
        "google_reviews_widget": check_google_reviews_widget(html),
        "medicare_certified": medicare_pass,
        "services_list": services_pass,
        "referral_page": referral_pass,
        "cms_star_rating": star_pass,
    }

    return {
        "url": final_url,
        "status": status,
        "checks": checks,
        "pagespeed_score": psi.get("score"),
        "pagespeed_low": psi.get("low"),
        "pagespeed_high": psi.get("high"),
        "pagespeed_runs": psi.get("scores"),
        "pagespeed_error": psi.get("error"),
        "services_offered": services_offered,
        "cms_star_rating": star_value,
        "platform": detect_platform(html),
        "grade": grade_website(checks),
    }


def main():
    parser = argparse.ArgumentParser(description="Home health website audit (hard mode)")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.url), indent=2))


if __name__ == "__main__":
    main()
