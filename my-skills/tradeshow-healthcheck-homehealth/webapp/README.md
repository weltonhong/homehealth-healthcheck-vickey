# Home Health Online Health Check - Streamlit Web App

Browser version of the home health trade show / cold-outreach health
check. Reuses the existing scripts in `../scripts/` (`health_check.py`,
`google_serp_rank.py`, `website_audit.py`, `pdf_generator.py`) without
rebuilding any logic.

CTA routes to **Vickey Lopez** (Vickey.Lopez@RingRingMarketing.com).

## Local run

```bash
cd my-skills/tradeshow-healthcheck-homehealth/webapp
pip install -r requirements.txt

# On Windows the underlying scripts also try a PowerShell fallback for env
# vars, so existing user env vars work without extra setup. On Mac/Linux,
# export them in your shell first:
export GOOGLE_API_KEY=...
export SCRAPINGBEE_API_KEY=...

streamlit run app.py
```

Open <http://localhost:8501>.

## Streamlit Cloud deploy

1. Push the clean slice repo (`weltonhong/homehealth-healthcheck-vickey`) to GitHub.
2. On <https://share.streamlit.io>, point a new app at:
   - **Repo:** weltonhong/homehealth-healthcheck-vickey
   - **Branch:** main
   - **Main file path:** `my-skills/tradeshow-healthcheck-homehealth/webapp/app.py`
3. In **App settings → Secrets**, add:
   ```toml
   GOOGLE_API_KEY = "AIza..."
   SCRAPINGBEE_API_KEY = "..."
   ```
4. Deploy. The webapp pulls secrets into `os.environ` at startup so the
   underlying scripts (which read env vars directly) pick them up.

## How it works

- `app.py` adds `../scripts/` to `sys.path` and imports `health_check` and
  `pdf_generator` directly.
- `health_check.run_health_check()` runs in a background thread. Its
  `print()` output is captured by a `_QueueWriter` and streamed to a
  `st.code()` placeholder so the rep watches the scan in real time.
- `pdf_generator.SCMM_LOGO_PATH` is monkey-patched to point at
  `webapp/assets/scmm_logo.jpg` so the PDF renders correctly in cloud
  environments where the original Windows D:\ share isn't available.
- `pdf_generator.get_desktop_path` is monkey-patched to a tempdir so the
  PDF is written to a server-writable location, then read back and
  offered via `st.download_button`.
- The Calendly QR code is regenerated fresh on every PDF build from the
  `CALENDLY_URL` constant in `pdf_generator.py`.

## Home health-specific behavior

- Search buckets: `home health [city]` and `home health agency [city]`
  per city, plus `medicare home health [home_city]` in the home city
  only (highest-intent payer-savvy signal).
- Reviews grading: same relative scale as homecare (A if more than top
  competitor OR 100+).
- Directory filter strips Care Compare (medicare.gov), homehealthcompare,
  Caring.com, A Place For Mom, AgingCare, and other senior-care lead-gen
  aggregators that dominate HH SERPs.
- Ad block: empty buckets framed as "open lane" opportunity.
- Website checks (10 graded): real photos, PageSpeed, About/Team page,
  intake form, schema, reviews widget, Medicare-certified mention,
  services list, referral source page, CMS Star Rating displayed.
  Platform reported as a non-graded data point.

## Notes

- ScrapingBee is required in cloud deployments. The Playwright fallback in
  `google_serp_rank.py` won't work on Streamlit Cloud (no Chromium install).
- No authentication. Anyone with the URL can run a scan. Add an auth layer
  before sharing publicly.
