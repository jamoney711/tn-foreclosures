"""
equity_enrichment.py
Estimates property equity using:
1. TN county assessor appraised value (free, via county open data portals)
2. Zillow Zestimate via unofficial scrape (fallback)
3. Loan amount from notice as the debt baseline

Equity estimate = estimated_value - original_loan_amount
Equity % = (equity / estimated_value) * 100
"""

import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime

# TN County Assessor API endpoints (open GIS/data portals)
# Many TN counties use Tyler Technologies iasWorld or ESRI GIS
COUNTY_ASSESSOR_APIS = {
    "Knox": "https://www.knoxcounty.org/apps/tax_search/",
    "Davidson": "https://www.padctn.org/",
    "Shelby": "https://www.assessor.shelby.tn.us/",
    "Hamilton": "https://www.hamiltontn.gov/departments/assessor/",
    "Rutherford": "https://www.assessment.state.tn.us/",
    # All counties fall back to TN state assessment portal
}

TN_STATE_ASSESSMENT_BASE = "https://www.assessment.state.tn.us/assessment/results.aspx"


def get_tn_state_assessment(address, county):
    """
    Query TN State Board of Equalization assessment lookup.
    Returns dict with appraised_value and assessed_value.
    """
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        # TN Assessment portal search
        search_url = "https://www.assessment.state.tn.us/assessment/results.aspx"
        params = {
            "county": county,
            "address": address,
        }
        
        resp = session.get(search_url, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        
        # Parse appraised value from response
        text = resp.text
        
        # Look for appraisal value patterns
        patterns = [
            r"Appraised Value[:\s]*\$?([\d,]+)",
            r"Total Appraised[:\s]*\$?([\d,]+)",
            r"Market Value[:\s]*\$?([\d,]+)",
        ]
        
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                value = int(m.group(1).replace(",", ""))
                return {
                    "source": "TN State Assessment",
                    "appraised_value": value,
                    "assessed_value": int(value * 0.25),  # TN assesses at 25% of appraised
                }
        
        return None
        
    except Exception as e:
        print(f"  [Assessor] Error for {address}: {e}")
        return None


def get_zillow_estimate(address, city, state="TN", zip_code=""):
    """
    Get Zillow Zestimate via scraping zillow.com search results.
    Uses public search page — no API key needed.
    """
    try:
        search_addr = f"{address}, {city}, {state} {zip_code}".strip()
        search_addr_encoded = search_addr.replace(" ", "+").replace(",", "%2C")
        
        url = f"https://www.zillow.com/homes/{search_addr_encoded}_rb/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        
        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=15)
        
        if resp.status_code != 200:
            return None
        
        text = resp.text
        
        # Look for Zestimate in page JSON
        patterns = [
            r'"zestimate"[:\s]*\{[^}]*"amount"[:\s]*([\d]+)',
            r'"price"[:\s]*([\d]+)',
            r'Zestimate[®™]?[:\s]*\$?([\d,]+)',
            r'"hdpData".*?"price":([\d]+)',
        ]
        
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                value = int(m.group(1).replace(",", ""))
                if 10000 < value < 50000000:  # sanity check
                    return {
                        "source": "Zillow",
                        "estimated_value": value,
                        "zillow_url": url,
                    }
        
        return None
        
    except Exception as e:
        print(f"  [Zillow] Error for {address}: {e}")
        return None


def calculate_equity(record):
    """
    Calculate equity for a single foreclosure record.
    Returns updated record with equity fields added.
    """
    address = record.get("property_address", "")
    city = record.get("property_city", "")
    zip_code = record.get("property_zip", "")
    county = record.get("county", "")
    
    loan_str = record.get("original_loan_amount", "")
    try:
        loan_amount = float(str(loan_str).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        loan_amount = 0
    
    if not address or not city:
        record["estimated_value"] = None
        record["equity_estimate"] = None
        record["equity_pct"] = None
        record["equity_source"] = None
        record["equity_flag"] = "insufficient_data"
        return record
    
    # Try TN State Assessor first
    assessment = get_tn_state_assessment(address, county)
    time.sleep(0.5)
    
    if assessment and assessment.get("appraised_value"):
        est_value = assessment["appraised_value"]
        source = "TN State Assessment"
    else:
        # Fallback to Zillow
        zillow = get_zillow_estimate(address, city, zip_code=zip_code)
        time.sleep(1)
        
        if zillow and zillow.get("estimated_value"):
            est_value = zillow["estimated_value"]
            source = "Zillow Estimate"
        else:
            # Last fallback: no data
            record["estimated_value"] = None
            record["equity_estimate"] = None
            record["equity_pct"] = None
            record["equity_source"] = "not_found"
            record["equity_flag"] = "no_value_data"
            return record
    
    # Calculate equity
    equity = est_value - loan_amount if loan_amount > 0 else None
    equity_pct = (equity / est_value * 100) if (equity is not None and est_value > 0) else None
    
    # Flag equity level
    if equity_pct is None:
        flag = "no_loan_data"
    elif equity_pct >= 40:
        flag = "HIGH_EQUITY"
    elif equity_pct >= 20:
        flag = "MODERATE_EQUITY"
    elif equity_pct >= 0:
        flag = "LOW_EQUITY"
    else:
        flag = "UNDERWATER"
    
    record["estimated_value"] = est_value
    record["equity_estimate"] = round(equity) if equity is not None else None
    record["equity_pct"] = round(equity_pct, 1) if equity_pct is not None else None
    record["equity_source"] = source
    record["equity_flag"] = flag
    
    return record


def enrich_all(records, max_records=None):
    """
    Enrich a list of foreclosure records with equity data.
    max_records: limit for testing (None = all)
    """
    print(f"Enriching {len(records)} records with equity data...")
    
    targets = records if max_records is None else records[:max_records]
    
    for i, record in enumerate(targets):
        addr = record.get("property_address", "N/A")
        print(f"  [{i+1}/{len(targets)}] {addr}...")
        
        try:
            enriched = calculate_equity(record)
            records[i] = enriched
            flag = enriched.get("equity_flag", "")
            val = enriched.get("estimated_value")
            eq = enriched.get("equity_pct")
            print(f"    -> ${val:,} est. | {eq}% equity | {flag}" if val else f"    -> {flag}")
        except Exception as e:
            print(f"    -> ERROR: {e}")
        
        time.sleep(0.3)  # Rate limiting
    
    return records


def run_enrichment(data_dir=None):
    """Load latest.json, enrich, save back."""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data"
    
    latest_path = data_dir / "latest.json"
    
    if not latest_path.exists():
        print("No latest.json found — run scraper first")
        return
    
    with open(latest_path) as f:
        records = json.load(f)
    
    # Only enrich records without equity data yet
    needs_enrichment = [r for r in records if "equity_flag" not in r or r["equity_flag"] == "insufficient_data"]
    print(f"{len(needs_enrichment)} records need equity enrichment")
    
    if not needs_enrichment:
        print("All records already enriched.")
        return records
    
    enriched = enrich_all(needs_enrichment)
    
    # Merge back
    enriched_map = {}
    for r in enriched:
        key = f"{r.get('property_address','')}-{r.get('auction_date','')}-{r.get('owner','')}"
        enriched_map[key] = r
    
    for i, r in enumerate(records):
        key = f"{r.get('property_address','')}-{r.get('auction_date','')}-{r.get('owner','')}"
        if key in enriched_map:
            records[i] = enriched_map[key]
    
    with open(latest_path, "w") as f:
        json.dump(records, f, indent=2)
    
    print(f"Enrichment complete. {len(enriched)} records updated.")
    return records


if __name__ == "__main__":
    run_enrichment()
