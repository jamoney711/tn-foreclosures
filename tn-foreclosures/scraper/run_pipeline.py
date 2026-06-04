"""
run_pipeline.py
Full pipeline: scrape -> enrich -> build dashboard data
Called by GitHub Actions every Friday.
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Add scraper dir to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape import scrape_all_notices, save_results
from equity_enrichment import run_enrichment


def build_dashboard_data(data_dir):
    """
    Build dashboard_data.json — a pre-processed summary for the frontend.
    Includes county/city aggregations, equity breakdowns, and auction calendar.
    """
    latest_path = data_dir / "latest.json"
    if not latest_path.exists():
        print("No latest.json — skipping dashboard build")
        return
    
    with open(latest_path) as f:
        records = json.load(f)
    
    # Aggregate by county
    county_map = {}
    city_map = {}
    auction_map = {}
    equity_breakdown = {"HIGH_EQUITY": 0, "MODERATE_EQUITY": 0, "LOW_EQUITY": 0, "UNDERWATER": 0, "no_data": 0}
    
    for r in records:
        county = r.get("county", "Unknown")
        city = r.get("property_city", "Unknown").strip() or "Unknown"
        auction_date = r.get("auction_date", "")
        equity_flag = r.get("equity_flag", "no_data")
        
        county_map.setdefault(county, {"count": 0, "cities": set(), "records": []})
        county_map[county]["count"] += 1
        county_map[county]["cities"].add(city)
        county_map[county]["records"].append(r)
        
        city_map.setdefault(city, {"count": 0, "county": county})
        city_map[city]["count"] += 1
        
        if auction_date:
            auction_map.setdefault(auction_date, []).append(r)
        
        if equity_flag in equity_breakdown:
            equity_breakdown[equity_flag] += 1
        else:
            equity_breakdown["no_data"] += 1
    
    # Convert sets to lists for JSON
    for county in county_map:
        county_map[county]["cities"] = sorted(county_map[county]["cities"])
        # Remove embedded records from summary (save space)
        del county_map[county]["records"]
    
    dashboard_data = {
        "generated_at": datetime.now().isoformat(),
        "total_records": len(records),
        "county_summary": county_map,
        "city_summary": city_map,
        "auction_calendar": {k: len(v) for k, v in auction_map.items()},
        "equity_breakdown": equity_breakdown,
        "records": records,  # Full records for filtering in frontend
    }
    
    # Save to data dir for dashboard to read
    out_path = data_dir / "dashboard_data.json"
    with open(out_path, "w") as f:
        json.dump(dashboard_data, f, indent=2)
    
    # Also copy to dashboard folder for GitHub Pages
    dashboard_dir = Path(__file__).parent.parent / "dashboard"
    dashboard_dir.mkdir(exist_ok=True)
    shutil.copy(out_path, dashboard_dir / "dashboard_data.json")
    
    print(f"Dashboard data built: {len(records)} records, {len(county_map)} counties, {len(city_map)} cities")
    return dashboard_data


def main():
    print("=" * 60)
    print(f"TN Foreclosures Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    # Step 1: Scrape
    print("\n[Step 1] Scraping foreclosurestn.com...")
    results = scrape_all_notices(days_back=7)
    
    if not results:
        print("WARNING: No results returned from scraper.")
        print("Building dashboard with existing data (if any)...")
    else:
        json_path, csv_path = save_results(results, data_dir)
        print(f"Scraped {len(results)} notices. Saved to {json_path.name}")
    
    # Step 2: Equity enrichment
    print("\n[Step 2] Running equity enrichment...")
    try:
        run_enrichment(data_dir)
    except Exception as e:
        print(f"Equity enrichment error (non-fatal): {e}")
    
    # Step 3: Build dashboard data
    print("\n[Step 3] Building dashboard data...")
    dashboard_data = build_dashboard_data(data_dir)
    
    if dashboard_data:
        print(f"Pipeline complete. {dashboard_data['total_records']} records in dashboard.")
    else:
        print("Pipeline complete (no new data).")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
