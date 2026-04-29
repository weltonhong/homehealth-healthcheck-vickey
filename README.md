# Home Health Online Health Check (Vickey Lopez)

Streamlit web app that runs a 60-90 second online presence audit on a
Medicare-certified home health agency at a trade show booth or for
cold-outreach prep, and produces a branded one-page Senior Care
Marketing Max PDF scorecard.

This is the deployable slice of the
`tradeshow-healthcheck-homehealth` skill from the internal Powerhouse
repo. It contains only the health check code -- no client data, no
other skills.

CTA routes to **Vickey Lopez** (Vickey.Lopez@RingRingMarketing.com).

> **Home health is distinct from non-medical home care and from hospice.**
> Different buyer journey, different regulatory framing, different
> search intent. This deploy is for Medicare-certified home health
> agencies (skilled nursing, PT/OT/ST, wound care, post-discharge
> care, intermittent skilled care).

## Run locally

```bash
cd my-skills/tradeshow-healthcheck-homehealth/webapp
pip install -r requirements.txt

# On Mac/Linux:
export GOOGLE_API_KEY=...
export SCRAPINGBEE_API_KEY=...

# On Windows (PowerShell):
# $env:GOOGLE_API_KEY="..."
# $env:SCRAPINGBEE_API_KEY="..."

streamlit run app.py
```

Open <http://localhost:8501>.

## Deploy to Streamlit Cloud

1. Push this repo to GitHub (already done if you're reading this on GitHub).
2. Go to <https://share.streamlit.io> -> **Create app** -> **Deploy from GitHub**.
3. Settings:
   - **Repository:** `weltonhong/homehealth-healthcheck-vickey`
   - **Branch:** `main`
   - **Main file path:** `my-skills/tradeshow-healthcheck-homehealth/webapp/app.py`
   - **Python version:** 3.12
4. Open **Advanced settings** -> **Secrets** and paste:
   ```toml
   GOOGLE_API_KEY = "AIzaSy..."
   SCRAPINGBEE_API_KEY = "..."
   ```
5. Click **Deploy**. First build takes 2-4 minutes.

Target URL: `homehealth-healthcheck-vickey.streamlit.app`

> **Do not click "Add Dev Container Folder" on this repo on GitHub.**
> The wizard auto-generates a devcontainer that points Streamlit at
> `google_serp_rank.py` (a CLI tool with required argparse args) and
> Streamlit Cloud picks up that hint, crash-looping on startup. We
> learned that the hard way on Brian's deploy. `.devcontainer/` is in
> `.gitignore` to block it at source — keep it that way.

## What gets scanned

| Check | Source |
|-------|--------|
| Google Reviews | Google Places API (homecare-equivalent grading scale) |
| Google 3-Pack (per bucket: home health + home health agency per city, plus medicare in home city) | Google SERP via UULE |
| Google SEO (per bucket) | ScrapingBee + UULE |
| Google Ads (per bucket) | Parsed from same SERP HTML; empty buckets framed as "open lane" |
| Website (10 HH-specific checks) | requests + PageSpeed Insights API |
| Reviews snapshot | Google + Facebook + Yelp |

Each check produces a letter grade. Overall grade is the average of
the graded checks; "Unable to verify" website audits are excluded.

## Search buckets

For every city the rep enters, we run **home health [city]** AND
**home health agency [city]**. For the home city only, we also run
**medicare home health [home_city]** because that's the highest-intent
payer-savvy search and the strongest signal of a family who has done
their homework.

## Home-health-vertical website checks (10 graded)

1. Real photos (no stock CDN, no generic alt text)
2. PageSpeed mobile score >= 50
3. About / team page with role hits (RN, LPN, PT, OT, ST, MSW, DPS, DON, etc.)
4. Intake form / scheduling widget
5. LocalBusiness or HomeHealthAgency schema
6. Google reviews widget
7. Medicare-certified mention (homepage or About/Services page)
8. Services list (skilled nursing, PT, OT, ST, MSW, HHA, wound care,
   IV therapy, post-discharge, telehealth, chronic disease, etc.)
9. Referral source page (dedicated workflow for hospitals, SNFs,
   physicians, case managers, discharge planners)
10. CMS Star Rating displayed (from Care Compare)

Plus platform fingerprinting (HealthcareSuccess, Stratus Interactive,
Hearst Health, BlueOrange Compass, plus generic WordPress / Squarespace
/ Wix / HubSpot CMS) as a non-graded data point.

## Repo layout

```
my-skills/
  tradeshow-healthcheck-homehealth/
    SKILL.md
    scripts/
      health_check.py        # Orchestrator - runs all checks in parallel
      google_serp_rank.py    # Real Google SERP via ScrapingBee
      website_audit.py       # HH-vertical homepage scrape + heuristics
      pdf_generator.py       # Branded SCMM one-page PDF + Calendly QR
      name_matcher.py        # Shared deathcare/senior-care name matcher
      verify_qr.py           # Decodes generated QR to confirm Calendly URL
    webapp/
      app.py                 # Streamlit UI
      requirements.txt
      assets/
        scmm_logo.jpg
      README.md
  quick-intel/
    scripts/
      google_intel.py        # Google Places lookup (target + competitors)
```

## API keys you need

| Key | What it powers | Where to get it |
|-----|----------------|-----------------|
| `GOOGLE_API_KEY` | Google Places + Geocoding + PageSpeed Insights | Google Cloud Console |
| `SCRAPINGBEE_API_KEY` | Real Google SERP rendering | scrapingbee.com |

Both keys must be set in `os.environ` (locally) or in Streamlit Cloud
**Secrets** (deployed).

## Calendly QR

The Calendly QR code on the bottom of the PDF is regenerated fresh on
every PDF build from `pdf_generator.CALENDLY_URL`. To verify:

```bash
python my-skills/tradeshow-healthcheck-homehealth/scripts/verify_qr.py
```

Output:
```
Expected: https://calendly.com/vickey-lopez/vickeylopezseniormarketingspecialist
Decoded:  https://calendly.com/vickey-lopez/vickeylopezseniormarketingspecialist
PASS: QR decodes to Vickey Lopez's Calendly URL
```

To swap reps later (Holly's and Brian's HH deploys), change the rep
constants block at the top of `pdf_generator.py` — `REP_NAME`,
`REP_EMAIL`, and `CALENDLY_URL`. `BRAND_LINE` stays the same across
all SCMM deploys.
