---
name: tradeshow-healthcheck-homehealth
description: "Trade show / cold-outreach booth tool for MEDICARE-CERTIFIED HOME HEALTH agencies (skilled nursing, PT/OT/ST, wound care, post-discharge, intermittent skilled care). Distinct from non-medical home care and from hospice. Runs a fast (60-90 second) online presence audit on a home health prospect across 2-3 cities they serve and prints a live scorecard, then generates a branded one-page Senior Care Marketing Max PDF. Scans Google reviews, 3-Pack (home health + home health agency), SEO organic, website (Medicare cert + services list + referral page + CMS Star Rating), and competitor ads in parallel. CTA routes to Vickey Lopez. Use when 'tradeshow healthcheck homehealth', 'health check home health', 'home health booth audit', 'home health trade show audit', 'health check [home health agency] [city] [state]'."
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# TRADESHOW HEALTH CHECK - HOME HEALTH

## What This Skill Does

Runs a fast online presence audit on a Medicare-certified home health agency at a trade show booth or for cold-outreach prep. The whole scan takes 60-90 seconds and produces:

1. A live scorecard printed to the terminal as each check completes (so the prospect sees it happening in real time at a booth)
2. A branded one-page Senior Care Marketing Max PDF saved to the Desktop

This is a fork of `tradeshow-healthcheck-homecare`, retooled for home health vocabulary, search intent (home health + home health agency + medicare home health), and website checks (Medicare certification, services list, referral source page, CMS Star Rating). The CTA still routes to Vickey Lopez.

## Home health vs home care vs hospice

These three verticals look adjacent but have completely different buyer journeys:

- **Home health (this skill)**: Medicare-certified, skilled care delivered at home. RNs, LPNs, PT/OT/ST therapists, home health aides, medical social workers. Most volume comes from REFERRAL SOURCES (hospitals, SNFs, physicians, discharge planners), not family self-referrals — though families also call, especially after a hospital discharge or new diagnosis. Episodes of care, CMS Star Ratings, Care Compare.
- **Home care** (`tradeshow-healthcheck-homecare`): Non-medical, private-pay. Companion care, ADL help, transportation. Family-pay and family-driven. Billable hours.
- **Hospice**: End-of-life care. Different regulatory framing again. Not covered by either skill.

Don't conflate. The vocabulary, search intent, website expectations, and revenue model differ enough that the same scan template would mis-label gaps.

## Input

**ALWAYS prompt the user for input before running. Never auto-fill, never assume, never use positional args from the slash command line.**

The rep is at a trade show booth typing the prospect's live answers. You must ask each question and wait for the answer.

### Required workflow

Ask each question on its own line, **one at a time**, blank, with **no pre-filled answers, no parenthetical suggestions, and no inferences**. Wait for the user's reply before asking the next question.

Order:

1. `Home health agency name:`
2. `Home city:`
3. `State (2-letter):`
4. `Second city (or skip):`
5. `Third city (or skip):`

**Hard rules:**
- Never infer the home city from the agency name. "Bayada Home Health" does NOT mean Philadelphia. Ask anyway.
- Never write parenthetical guesses after a question.
- Never batch multiple questions in one prompt. One question, wait, next question.
- After each user answer, the next message is just the next blank question label - no acknowledgment text, no restating what they said.

If the user answers "skip", "none", "n/a", or leaves a city blank, skip that city. 2-3 cities is the realistic norm — Medicare-defined service areas are typically larger than non-medical home care territories but smaller than cemeteries draw from.

After collecting all inputs, run the script with the collected values.

### Why prompt every time

The prospect's service area changes with every booth conversation. Auto-filling or guessing breaks the booth flow.

## How To Run

```bash
python my-skills/tradeshow-healthcheck-homehealth/scripts/health_check.py "<agency>" "<city1>" "<state>" ["<city2>"] ["<city3>"]
```

Example:
```bash
python my-skills/tradeshow-healthcheck-homehealth/scripts/health_check.py "Bayada Home Health Care" "Philadelphia" "PA"
```

The script:
1. Pulls Google Places data for the prospect + top home health competitors (from City1)
2. Fans out parallel checks: 3-Pack (per bucket: home health + home health agency per city, plus medicare home health in home city), SEO (per bucket), Website, Reviews
3. Builds the Ads check from each bucket's SERP HTML
4. Prints a live scorecard to stdout as each check completes
5. Saves raw data to `temp_health_check.json` next to the script
6. Generates a branded Senior Care Marketing Max PDF on the OneDrive Desktop

## Search Queries

| Bucket | Query | Where it runs |
|---|---|---|
| Home health (primary) | `home health [city] [state]` | Every city |
| Home health agency (secondary) | `home health agency [city] [state]` | Every city |
| Medicare home health (tertiary) | `medicare home health [home_city] [state]` | Home city only |

Home health is the family-and-discharge-planner search. "Home health agency" is the more deliberate, often-referral-source-driven search. "Medicare home health" is the highest-intent payer-savvy search and a strong signal of a family who's done their homework — we run it in the home city only to keep scan time under 90 seconds.

## What It Scans

| Check | Source | Output |
|-------|--------|--------|
| Google Reviews | google_intel.py (Google Places API) | Target reviews + top competitor reviews + gap. Same relative grading scale as homecare (A if more than top competitor OR 100+). |
| Google 3-Pack | Per-bucket Google SERP -> Local Map Pack | In/out of top 3 from each bucket. |
| SEO Organic | ScrapingBee + UULE per bucket (Playwright fallback) | Rank for each bucket. Heavy directory filtering — Care Compare and aggregator sites dominate HH SERPs. |
| Website | requests.get + PageSpeed Insights API + subpage fetches | 10 hard checks: real photos, PageSpeed mobile, About/team page, intake form, LocalBusiness schema, Google reviews widget, Medicare-certified mention, services list, referral source page, CMS Star Rating displayed. Detects platform (HealthcareSuccess, Stratus, Hearst Health, BlueOrange Compass, plus generic WordPress/Squarespace/Wix). |
| Reviews Snapshot | Google Places + DDG search | Google + Facebook + Yelp counts/links |
| Competitor Ads | Same SERP HTML from SEO check; parses `div#tads` | Real Google ad advertisers per bucket. Domain-only matching filters out corporate operator ads (Amedisys, LHC Group, Encompass, BAYADA corporate, Interim). |

## Grading Scale

| Area | A | B | C | D | F |
|------|---|---|---|---|---|
| Reviews | 100+ OR more than top competitor | 50-99 | 20-49 | 5-19 | 0-4 |
| 3-Pack | Found in all bucket combos | Found in most | Found in 1 | - | Not found anywhere |
| SEO | Top 10 in all buckets | Top 10 in most | Top 10 in 1 | - | Not in top 10 anywhere |
| Ads | Prospect running in all buckets | Running in most | Running in 1 | - | Not running in any |
| Website | 10/10 checks pass (or N/A if blocked) | 7-9 | 4-6 | 1-3 | 0 |
| Overall | Average of all grades except those marked "Unable to verify" |

**No advertisers detected:** Many home health agencies don't run paid ads — referral-source driven. The scorecard frames empty buckets as "open lane" opportunity rather than failure (same as cemetery).

## Unable to Verify (Website)

When the prospect's website returns HTTP 403, times out, or fails SSL, the website check returns `unverified: true` instead of grading F. The terminal shows "Unable to verify -- Website blocked our scan" and the PDF shows grade "N/A". This grade is excluded from the overall grade calculation.

## On-Screen Output Format

```
============================================
ONLINE HEALTH CHECK | Bayada Home Health Care Philadelphia, PA
============================================

GOOGLE REVIEWS:
  74 reviews, 4.5 stars

TOP COMPETITOR:
  Penn Home Care -- 142 reviews, 4.7 stars

REVIEW GAP:
  68 reviews behind (SIGNIFICANT)

GOOGLE LOCAL MAP RANKINGS:
  home health / Philadelphia:        FOUND rank 2 (Top 3: ...)
  home health agency / Philadelphia: NOT FOUND (Top 3: ...)
  medicare home health / Philadelphia: FOUND rank 3 (Top 3: ...)
  Grade: B

GOOGLE ORGANIC RANKINGS (SEO):
  home health / Philadelphia PA:        Rank 5
  home health agency / Philadelphia PA: Not in top 10
  medicare home health / Philadelphia PA: Rank 8
  Grade: B

GOOGLE ADS:
  home health / Philadelphia: Penn Home Care, Amedisys
  home health agency / Philadelphia: No ads detected (open lane)
  medicare home health / Philadelphia: Penn Home Care
  Bayada Home Health Care: Not running
  Grade: F

WEBSITE:
  Real photos:               Yes
  PageSpeed mobile:          47/100 (FAIL)
  About/Team page:           Yes
  Intake form:               Yes
  LocalBusiness schema:      Yes
  Google reviews widget:     No
  Medicare certified:        Yes
  Services list:             Yes
  Referral source page:      No
  CMS Star Rating displayed: No
  Platform:                  HealthcareSuccess
  Grade: B

REVIEWS SNAPSHOT:
  Google:   74 reviews, 4.5 stars
  Facebook: Page found
  Yelp:     ? reviews

============================================
OVERALL GRADE: C    (scan time: 64s)
============================================
```

## PDF Output

Saved to OneDrive Desktop as:
```
HealthCheck_<AgencyName>_<YYYY-MM-DD>.pdf
```

Contents:
- SCMM brand header
- Agency name + scan date
- Big overall grade banner
- 5-row scorecard with grades and per-bucket details
- 2 specific recommendations targeting the worst grades
- Footer CTA bar with Vickey Reese contact + Calendly QR (regenerated fresh from CALENDLY_URL on every build)

## CTA / Footer

Footer copy:
> Every week these gaps stay open, hospitals and discharge planners are referring patients to your competitors, and Medicare-eligible families searching online are calling someone else. We close these gaps for home health agencies like yours. Call today.

Contact:
- Vickey Lopez, Sales Consultant
- Vickey.Lopez@RingRingMarketing.com
- Senior Care Marketing Max | (888) 383-2848
- QR -> Vickey's Calendly

## Files

```
my-skills/tradeshow-healthcheck-homehealth/
  SKILL.md
  scripts/
    health_check.py      # Main orchestrator (run this)
    google_serp_rank.py  # Real-Google SERP rank checker (ScrapingBee + Playwright fallback)
    name_matcher.py      # Shared deathcare/senior-care name matcher (matcher fix from 97e3e0b)
    website_audit.py     # HH-specific homepage scrape + heuristics
    pdf_generator.py     # Reportlab branded SCMM PDF, regenerates QR from CALENDLY_URL at build time
    verify_qr.py         # Decodes generated QR with pyzbar to confirm rep's Calendly URL
  webapp/
    app.py
    requirements.txt
    assets/
```

## Dependencies

- `reportlab` (PDF) - install with `pip install reportlab`
- `qrcode[pil]` (Calendly QR) - install with `pip install "qrcode[pil]"`
- `requests` (HTTP)
- `rapidfuzz` (matcher fuzzy fallback)
- `playwright` (SERP fallback) - install with `pip install playwright && playwright install chrome`
- `GOOGLE_API_KEY` env var (Places + Geocoding)
- `SCRAPINGBEE_API_KEY` env var (preferred SERP backend)
- Reuses `my-skills/quick-intel/scripts/google_intel.py` (with `--vertical "home health"`)

## SERP Backend Selection

Same two-tier backend as the other tradeshow-healthcheck skills:

1. **ScrapingBee with `custom_google=true` + UULE** - Primary path. ~25 credits per query. With 2 cities (4 buckets) + medicare in the home city (1 bucket), that's ~125 credits per scan. With 3 cities (6+1 = 7 buckets), ~175 credits per scan.
2. **Playwright with stealth + UULE + persisted cookies** - Fallback if `SCRAPINGBEE_API_KEY` is not set OR ScrapingBee returns an error.

Never falls back to DuckDuckGo.

## Boundaries

| Always | Ask First | Never |
|--------|-----------|-------|
| Run all checks in parallel | Before changing the grading scale | Block on a single slow check past 30 seconds |
| Print results live as they arrive | Before adding a new search bucket | Fabricate review counts or ranks |
| Save the PDF to OneDrive Desktop | Before changing recommendation copy | Conflate corporate operator ads (Amedisys, LHC, Encompass, BAYADA corporate, Interim) with the local home health agency running ads |
| Use only data returned by tool calls in this session | | Skip the live terminal output (the prospect needs to see it) |
| Treat home health as distinct from home care and hospice | | Mix vocabulary across the three verticals |

## Why This Exists

At a home health industry convention or during cold outreach, Vickey walks up to a prospect's booth (or dials a list of Medicare-certified agencies), asks for the agency name and 1-2 nearby cities, types one command, and 60-90 seconds later hands the administrator a printed scorecard with their grades, their gaps across their service area, and a call to action. The whole thing happens while they are still on the phone or standing there.
