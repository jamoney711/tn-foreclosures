"""
foreclosurestn.com scraper - v2
No date form interaction. Navigates detail pages in same tab.
"""

import json
import csv
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

TN_COUNTIES = [
    "Anderson","Bedford","Benton","Bledsoe","Blount","Bradley","Campbell",
    "Cannon","Carroll","Carter","Cheatham","Chester","Claiborne","Clay",
    "Cocke","Coffee","Crockett","Cumberland","Davidson","Decatur","DeKalb",
    "Dickson","Dyer","Fayette","Fentress","Franklin","Gibson","Giles",
    "Grainger","Greene","Grundy","Hamblen","Hamilton","Hancock","Hardeman",
    "Hardin","Hawkins","Haywood","Henderson","Henry","Hickman","Houston",
    "Humphreys","Jackson","Jefferson","Johnson","Knox","Lake","Lauderdale",
    "Lawrence","Lewis","Lincoln","Loudon","Macon","Madison","Marion",
    "Marshall","Maury","McMinn","McNairy","Meigs","Monroe","Montgomery",
    "Moore","Morgan","Obion","Overton","Perry","Pickett","Polk","Putnam",
    "Rhea","Roane","Robertson","Rutherford","Scott","Sequatchie","Sevier",
    "Shelby","Smith","Stewart","Sullivan","Sumner","Tipton","Trousdale",
    "Unicoi","Union","Van Buren","Warren","Washington","Wayne","Weakley",
    "White","Williamson","Wilson"
]

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE_URL = "https://foreclosurestn.com"


def parse_notice_text(text):
    data = {
        "owner": "", "trustee": "", "beneficiary": "",
        "original_loan_amount": "", "property_address": "",
        "property_city": "", "property_state": "TN", "property_zip": "",
        "auction_date": "", "auction_time": "", "auction_location": "",
        "parcel_id": "",
    }

    for pat in [
        r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated|\s+herein)",
        r"(?:Grantor|Maker|Borrower)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["owner"] = m.group(1).strip().title()
            break

    for pat in [
        r"(?:property located at|situated at|known as|being known as)[:\s]+(\d+[^\n,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n,]*)",
        r"(\d{3,5}\s+[A-Z][A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy)\.?)",
    ]:
        m = re.search(pat, t
