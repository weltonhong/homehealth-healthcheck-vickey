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
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests


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


def fetch_page(url, timeout=15):
    if not url:
        return None, None, "no url"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r.text, r.status_code, r.url
    except Exception as e:
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
    pattern = re.compile(r'<a[^>]+href="([^"]+)"', re.IGNORECASE)
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        href_low = href.lower()
        for kw in url_keywords:
            if kw in href_low:
                if href.startswith("http"):
                    return href
                if href.startswith("//"):
                    return "https:" + href
                if href.startswith("/"):
                    return base_url + href
                return urllib.parse.urljoin(base_url + "/", href)
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
        except Exception:
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


def check_pagespeed(url, api_key, timeout=90):
    """Returns dict with score (0-100) and pass (>=50). Retries once."""
    if not api_key:
        sys.stderr.write("[pagespeed] no GOOGLE_API_KEY available\n")
        return {"score": None, "pass": None, "error": "no api key"}
    if not url:
        return {"score": None, "pass": None, "error": "no url"}

    psi_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "strategy": "mobile",
        "category": "performance",
        "key": api_key,
    }

    last_error = None
    for attempt in (1, 2):
        try:
            r = requests.get(psi_url, params=params, timeout=timeout)
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}: {r.text[:160]}"
                sys.stderr.write(
                    f"[pagespeed] attempt {attempt} failed for {url}: {last_error}\n"
                )
                continue
            data = r.json()
            score = (
                data.get("lighthouseResult", {})
                .get("categories", {})
                .get("performance", {})
                .get("score")
            )
            if score is None:
                last_error = "no score in response"
                sys.stderr.write(
                    f"[pagespeed] attempt {attempt} returned no score for {url}\n"
                )
                continue
            score_pct = round(score * 100)
            return {"score": score_pct, "pass": score_pct >= 50}
        except Exception as e:
            last_error = str(e)[:200]
            sys.stderr.write(
                f"[pagespeed] attempt {attempt} exception for {url}: {last_error}\n"
            )

    return {"score": None, "pass": None, "error": last_error}


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
    "calendly.com", "acuityscheduling", "squareup.com/appointments",
    "jotform.com", "gravityforms", "wpforms", "wpcf7", "contact-form-7",
    "hubspot.com/forms", "hsforms.com", "typeform.com", "ninjaforms",
    "formstack", "fluentform", "wsform", "fluent-form", "gform_wrapper",
    "elfsight-app-form",
]


def check_intake_form(html):
    """Pass if a real intake form (3+ visible fields) or scheduling widget."""
    html_lower = html.lower()
    for h in SCHEDULING_HINTS:
        if h in html_lower:
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
    comes from referral sources, not family self-referrals — missing
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
    Care Compare star rating. Also captures the numeric value if shown."""
    if not html:
        return False, None
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
    if not real:
        return "F"
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
    if status and status >= 400:
        return {
            "url": url,
            "error": f"HTTP {status}",
            "checks": {},
            "grade": "F",
        }

    base_url = base_origin(final_url)
    api_key = get_google_api_key()

    with ThreadPoolExecutor(max_workers=6) as ex:
        psi_future = ex.submit(check_pagespeed, final_url, api_key)
        team_future = ex.submit(check_about_team, html, base_url)
        medicare_future = ex.submit(check_medicare_certified, html, base_url)
        services_future = ex.submit(check_services_list, html, base_url)
        referral_future = ex.submit(check_referral_page, html, base_url)

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
