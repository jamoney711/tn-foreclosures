# TN Foreclosures — Diamond Home Buyers Intelligence Dashboard

Automated weekly scraper that pulls **all Tennessee foreclosure notices** from [foreclosurestn.com](https://foreclosurestn.com), enriches them with property value + equity estimates, and publishes a filterable dashboard via GitHub Pages.

---

## 🔧 Setup (One-Time)

### 1. Create the repository

Create a **new public repo** on GitHub named `tn-foreclosures` under your account `jamoney711`.

```
https://github.com/new
```

- Name: `tn-foreclosures`
- Public: ✅
- Initialize with README: No

### 2. Push this code

```bash
git init
git remote add origin https://github.com/jamoney711/tn-foreclosures.git
git add .
git commit -m "Initial setup"
git push -u origin main
```

### 3. Enable GitHub Pages

1. Go to repo → **Settings** → **Pages**
2. Source: `Deploy from a branch`
3. Branch: `gh-pages` / `/ (root)`
4. Click **Save**

Your dashboard will be live at:
```
https://jamoney711.github.io/tn-foreclosures/
```

### 4. Enable GitHub Actions

1. Go to repo → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**
3. The workflow runs **every Friday at 6:00 AM CT** automatically

### 5. Run your first scrape manually

Go to **Actions** → `TN Foreclosures Weekly Scrape` → **Run workflow** → **Run workflow**

This triggers an immediate scrape so you don't have to wait until Friday.

---

## 📋 What Gets Scraped

| Field | Source |
|-------|--------|
| Property Owner (deed of trust grantor) | Notice text |
| Full property address (street, city, state, zip) | Notice text |
| Auction date + time | Notice text |
| Trustee / Substitute Trustee | Notice text |
| Beneficiary / Lender | Notice text |
| Original loan amount | Notice text |
| Parcel ID | Notice text |
| Estimated property value | TN State Assessor → Zillow fallback |
| Equity estimate ($) | Calculated |
| Equity % | Calculated |

---

## 📊 Dashboard Features

- **Filter by county** — all 95 TN counties
- **Filter by city** — top cities by volume
- **Filter by auction date** — calendar bar + date range picker
- **Filter by equity flag** — High / Moderate / Low / Underwater / No Data
- **Full-text search** — owner name, address, city, lender
- **Sort** by auction date, county, equity %, owner name
- **Click any row** to expand full detail with links to:
  - Google Maps
  - Zillow listing
  - TN State Assessment lookup
  - Original notice source
- **Export to CSV** — filtered results only

---

## 🏗 Project Structure

```
tn-foreclosures/
├── .github/
│   └── workflows/
│       └── scrape.yml          # Runs every Friday at 6 AM CT
├── scraper/
│   ├── scrape.py               # Main Playwright scraper (all 95 counties)
│   ├── equity_enrichment.py    # Assessor + Zillow equity lookups
│   └── run_pipeline.py         # Pipeline runner (scrape → enrich → build)
├── dashboard/
│   ├── index.html              # Dashboard UI (deployed to GitHub Pages)
│   └── dashboard_data.json     # Auto-generated data file
├── data/
│   ├── latest.json             # Rolling 90-day record store
│   └── foreclosures_YYYY-MM-DD.json  # Weekly snapshots
├── requirements.txt
└── README.md
```

---

## ⚙️ How It Works

1. **Every Friday 6 AM CT**, GitHub Actions spins up an Ubuntu runner
2. Playwright launches headless Chromium and navigates to foreclosurestn.com
3. For each of the 95 TN counties, it searches the last 7 days and collects all notice detail pages
4. Raw notice text is parsed with regex to extract structured fields
5. Equity enrichment queries the TN State Assessment portal and Zillow as fallback
6. Results are merged into `latest.json` (rolling 90-day window, deduplicated)
7. `dashboard_data.json` is rebuilt with aggregates and pushed to the repo
8. GitHub Actions deploys the `dashboard/` folder to GitHub Pages

---

## 🔁 Schedule

| Event | Frequency |
|-------|-----------|
| Scrape run | Every Friday, 6:00 AM CT |
| Data window | Last 7 days per run |
| Dashboard retention | 90 days rolling |

---

## 🛠 Troubleshooting

**"No results" on first run?**
The site uses ASP.NET session cookies and JavaScript postbacks. If Playwright can't get through, check the Actions log for errors. You may need to adjust selectors in `scrape.py` if the site updates its HTML.

**Equity shows "No Data"?**
TN Assessment portal and Zillow both have rate limits. Records without addresses won't be enrichable. Re-run enrichment manually:
```bash
cd scraper && python equity_enrichment.py
```

**GitHub Pages not showing?**
Make sure you enabled Pages (Step 3 above) and that the `gh-pages` branch was created by the action.
