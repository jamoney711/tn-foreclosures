import json,csv,time,re
from datetime import datetime,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
COUNTY_INDEX={"Anderson":0,"Bedford":1,"Benton":2,"Bledsoe":3,"Blount":4,"Bradley":5,"Campbell":6,"Cannon":7,"Carroll":8,"Carter":9,"Cheatham":10,"Chester":11,"Claiborne":12,"Clay":13,"Cocke":14,"Coffee":15,"Crockett":16,"Cumberland":17,"Davidson":18,"Decatur":19,"DeKalb":20,"Dickson":21,"Dyer":22,"Fayette":23,"Fentress":24,"Franklin":25,"Gibson":26,"Giles":27,"Grainger":28,"Greene":29,"Grundy":30,"Hamblen":31,"Hamilton":32,"Hancock":33,"Hardeman":34,"Hardin":35,"Hawkins":36,"Haywood":37,"Henderson":38,"Henry":39,"Hickman":40,"Houston":41,"Humphreys":42,"Jackson":43,"Jefferson":44,"Johnson":45,"Knox":46,"Lake":47,"Lauderdale":48,"Lawrence":49,"Lewis":50,"Lincoln":51,"Loudon":52,"Macon":53,"Madison":54,"Marion":55,"Marshall":56,"Maury":57,"McMinn":58,"McNairy":59,"Meigs":60,"Monroe":61,"Montgomery":62,"Moore":63,"Morgan":64,"Obion":65,"Overton":66,"Perry":67,"Pickett":68,"Polk":69,"Putnam":70,"Rhea":71,"Roane":72,"Robertson":73,"Rutherford":74,"Scott":75,"Sequatchie":76,"Sevier":77,"Shelby":78,"Smith":79,"Stewart":80,"Sullivan":81,"Sumner":82,"Tipton":83,"Trousdale":84,"Unicoi":85,"Union":86,"Van Buren":87,"Warren":88,"Washington":89,"Wayne":90,"Weakley":91,"White":92,"Williamson":93,"Wilson":94}
TN_COUNTIES=list(COUNTY_INDEX.keys())
OUTPUT_DIR=Path(__file__).parent.parent/"data"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE_URL="https://foreclosurestn.com"
def parse_notice_text(text):
    data={"owner":"","trustee":"","beneficiary":"","original_loan_amount":"","property_address":"","property_city":"","property_state":"TN","property_zip":"","auction_date":"","auction_time":"","auction_location":"","parcel_id":""}
    for pat in [r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated|\s+herein)",r"(?:Grantor|Maker|Borrower)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["owner"]=m.group(1).strip().title()
            break
    for pat in [r"(?:property located at|situated at|known as|being known as)[:\s]+(\d+[^\n,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n,]*)",r"(\d{3,5}\s+[A-Z][A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy)\.?)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["property_address"]=m.group(1).strip()
            break
    for pat in [r"([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)[,\s]+(\d{5})",r"([A-Z][a-zA-Z ]+),\s*TN\s*(\d{5})"]:
        m=re.search(pat,text)
        if m:
            data["property_city"]=m.group(1).strip()
            data["property_zip"]=m.group(2).strip()
            break
    for pat in [r"(?:sale date|auction date|will be sold on|sold on)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})",r"([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:[,\s]+at\s+(\d{1,2}:\d{2}\s*[AaPp][Mm]))?"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["auction_date"]=m.group(1).strip()
            if m.lastindex and m.lastindex>=2 and m.group(2):
                data["auction_time"]=m.group(2).strip()
            break
    m=re.search(r"\$\s*([\d,]+(?:\.\d{2})?)",text)
    if m:
        data["original_loan_amount"]=m.group(1).replace(",","")
    for pat in [r"(?:Substitute Trustee|substitute trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s)",r"Trustee[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["trustee"]=m.group(1).strip()
            break
    for pat in [r"(?:beneficiary|lender|mortgagee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",r"(?:in favor of|payable to)\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["beneficiary"]=m.group(1).strip()
            break
    m=re.search(r"(?:Map|Parcel|Tax Map|Parcel ID|PIN)[:\s#]+([0-9\-\.A-Za-z]+)",text,re.IGNORECASE)
    if m:
        data["parcel_id"]=m.group(1).strip()
    return data
def scrape_county(page,county):
    idx=COUNTY_INDEX[county]
    cb_name="ctl00$ContentPlaceHolder1$as1$lstCounty$"+str(idx)
    links=[]
    try:
        page.goto(BASE_URL+"/Search.aspx",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_load_state("networkidle",timeout=15000)
        page.evaluate("__doPostBack('"+cb_name+"','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(1.5)
        for sel in ["a[href*='NoticeDetail']","a[href*='Detail.aspx']","a[href*='notice']","table a[href]"]:
            found=page.locator(sel)
            if found.count()>0:
                for i in range(found.count()):
                    href=found.nth(i).get_attribute("href") or ""
                    if href:
                        full=href if href.startswith("http") else BASE_URL+"/"+href.lstrip("/")
                        links.append(full)
                break
        if not links:
            rows=page.locator("table tbody tr")
            for i in range(rows.count()):
                txt=rows.nth(i).text_content() or ""
                if len(txt.strip())>80:
                    links.append({"inline":txt.strip()})
        print("    ["+county+"] "+str(len(links))+" notices")
    except Exception as e:
        print("    ["+county+"] ERROR: "+str(e))
    results=[]
    for item in links:
        try:
            if isinstance(item,str):
                page.goto(item,wait_until="domcontentloaded",timeout=20000)
                text=page.locator("body").text_content() or ""
                parsed=parse_notice_text(text)
                parsed["source_url"]=item
            else:
                parsed=parse_notice_text(item.get("inline",""))
                parsed["source_url"]=""
            parsed["county"]=county
            parsed["scraped_date"]=datetime.now().strftime("%Y-%m-%d")
            results.append(parsed)
            time.sleep(0.5)
        except Exception as e:
            print("    Notice error: "+str(e))
    return results
def is_recent(date_str,days=7):
    if not date_str:
        return True
    try:
        d=datetime.strptime(date_str,"%B %d, %Y")
        return d>=datetime.now()-timedelta(days=days)
    except:
        return True
def scrape_all_notices(days_back=7):
    print("Scrape started")
    all_results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",viewport={"width":1280,"height":900})
        context.set_default_timeout(20000)
        page=context.new_page()
        try:
            page.goto(BASE_URL+"/",wait_until="domcontentloaded",timeout=30000)
            time.sleep(2)
            print("Session ready")
        except Exception as e:
            print("Warmup: "+str(e))
        for i,county in enumerate(TN_COUNTIES):
            print("["+str(i+1)+"/95] "+county+"...")
            try:
                records=scrape_county(page,county)
                records=[r for r in records if is_recent(r.get("auction_date",""),days_back)]
                all_results.extend(records)
                print("    -> "+str(len(records))+" kept")
            except Exception as e:
                print("    FAIL: "+str(e))
            time.sleep(1)
        browser.close()
    print("Total: "+str(len(all_results)))
    return all_results
def save_results(results,output_dir=OUTPUT_DIR):
    ts=datetime.now().strftime("%Y-%m-%d")
    json_path=output_dir/("foreclosures_"+ts+".json")
    with open(json_path,"w") as f:
        json.dump(results,f,indent=2)
    csv_path=output_dir/("foreclosures_"+ts+".csv")
    if results:
        fields=["county","owner","property_address","property_city","property_state","property_zip","auction_date","auction_time","original_loan_amount","beneficiary","trustee","parcel_id","scraped_date","source_url"]
        with open(csv_path,"w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
            w.writeheader()
            w.writerows(results)
    latest_path=output_dir/"latest.json"
    existing=[]
    if latest_path.exists():
        try:
            existing=json.load(open(latest_path))
        except:
            pass
    seen=set()
    merged=[]
    for r in existing+results:
        key=str(r.get("property_address",""))+"-"+str(r.get("auction_date",""))+"-"+str(r.get("owner",""))
        if key not in seen:
            seen.add(key)
            merged.append(r)
    cutoff=datetime.now()-timedelta(days=90)
    merged=[r for r in merged if datetime.strptime(r.get("scraped_date","2000-01-01"),"%Y-%m-%d")>cutoff]
    with open(latest_path,"w") as f:
        json.dump(merged,f,indent=2)
    print("Saved - latest.json: "+str(len(merged))+" records")
    return json_path,csv_path
if __name__=="__main__":
    results=scrape_all_notices(days_back=7)
    save_results(results)
