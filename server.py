import os
import threading
import time
import requests
import csv
import io
import pypdf
import base64
import json
from flask import Flask, request, render_template, jsonify
from datetime import datetime

app = Flask(__name__)

# Constants
COUNTY = "Contra Costa County, CA"
START_ADDRESS = "2505 Dean Lesher Dr, Concord, CA"
ALWAYS_INCLUDE_ADDRESS = "923 Pacific Ct, Walnut Creek, CA"
GITHUB_REPO = "stephend-csu/newspaper-v3"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def extract_addresses_from_pdf(pdf_stream):
    reader = pypdf.PdfReader(pdf_stream)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    
    addresses = {}
    current_street = ""
    
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if parts[0].isdigit() and current_street:
            house_num = parts[0]
            if len(parts) > 1:
                newspaper = parts[1]
                full_address = f"{house_num} {current_street.title()}"
                if full_address not in addresses:
                    addresses[full_address] = set()
                addresses[full_address].add(newspaper)
        else:
            if "Route:" not in line and len(line) > 3:
                current_street = line
                
    result = []
    for addr, papers in addresses.items():
        result.append({
            "address": addr,
            "newspapers": " ".join(sorted(list(papers)))
        })
    return result

def validate_address(address):
    # Try Census Geocoder
    census_url = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
    census_params = {
        "address": f"{address}, Contra Costa County, CA",
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json"
    }
    
    census_city = None
    census_lat = None
    census_lon = None
    census_found = False
    
    try:
        resp = requests.get(census_url, params=census_params, timeout=10)
        data = resp.json()
        matches = data.get('result', {}).get('addressMatches', [])
        if matches:
            match = matches[0]
            geographies = match.get('geographies', {})
            counties = geographies.get('Counties', [])
            is_contra_costa = any("Contra Costa" in c.get('BASENAME', '') for c in counties)
            if is_contra_costa:
                components = match.get('addressComponents', {})
                census_city = components.get('city', '')
                coords = match.get('coordinates', {})
                census_lon = coords.get('x')
                census_lat = coords.get('y')
                census_found = True
    except Exception as e:
        print(f"Census error for {address}: {e}")

    # Try Nominatim
    nom_url = f"https://nominatim.openstreetmap.org/search?q={address}, Contra Costa County, CA&format=json&limit=1&addressdetails=1"
    headers = {'User-Agent': 'NewspaperApp/1.0'}
    
    nom_city = None
    nom_lat = None
    nom_lon = None
    nom_found = False
    
    try:
        resp = requests.get(nom_url, headers=headers, timeout=10)
        data = resp.json()
        if data:
            match = data[0]
            addr_details = match.get('address', {})
            nom_city = addr_details.get('city') or addr_details.get('town') or addr_details.get('village') or ''
            nom_lat = float(match.get('lat'))
            nom_lon = float(match.get('lon'))
            nom_found = True
    except Exception as e:
        print(f"Nominatim error for {address}: {e}")
        
    time.sleep(1) # Rate limit for Nominatim
    
    if census_found and nom_found:
        return {"status": "valid", "city": census_city, "lat": census_lat, "lon": census_lon, "confidence": "high", "reason": "Found by both APIs"}
    elif census_found:
        return {"status": "valid", "city": census_city, "lat": census_lat, "lon": census_lon, "confidence": "medium", "reason": "Only found by Census"}
    elif nom_found:
        return {"status": "doubt", "city": nom_city, "lat": nom_lat, "lon": nom_lon, "confidence": "low", "reason": "Only found by Nominatim"}
    else:
        return {"status": "problem", "city": "", "lat": None, "lon": None, "confidence": "none", "reason": "Not found in Contra Costa County"}

@app.route('/upload', methods=['POST'])
def upload():
    if 'pdf_file' not in request.files:
        return "No file uploaded", 400
        
    file = request.files['pdf_file']
    if file.filename == '':
        return "No file selected", 400
        
    if file and file.filename.endswith('.pdf'):
        raw_addresses = extract_addresses_from_pdf(file.stream)
        
        valid_list = []
        doubt_list = []
        problem_list = []
        counts_dict = {}
        
        for item in raw_addresses:
            addr = item['address']
            papers = item['newspapers']
            
            # Count newspapers
            for p in papers.split():
                if p:
                    counts_dict[p] = counts_dict.get(p, 0) + 1
                    
            val_res = validate_address(addr)
            
            result_item = {
                "address": addr,
                "city": val_res['city'],
                "newspapers": papers,
                "lat": val_res['lat'],
                "lon": val_res['lon'],
                "confidence": val_res['confidence'],
                "reason": val_res['reason']
            }
            
            if val_res['status'] == 'valid':
                valid_list.append(result_item)
            elif val_res['status'] == 'doubt':
                doubt_list.append(result_item)
            else:
                problem_list.append(result_item)
                
        # Select 2-3 lowest confidence for doubt (if doubt has space)
        # Any 'medium' from valid could be moved to doubt if doubt list is empty
        # But instructions: "Select 2-3 lowest confidence addresses for the doubt section"
        all_found = valid_list + doubt_list
        all_found.sort(key=lambda x: {"low": 1, "medium": 2, "high": 3}.get(x['confidence'], 4))
        
        doubt_list = all_found[:3] if len(all_found) >= 3 else all_found
        valid_list = [x for x in all_found if x not in doubt_list]
        
        return render_template('review.html', valid=valid_list, doubt=doubt_list, problem=problem_list, newspaper_counts=counts_dict)
        
    return "Invalid file format. Please upload a PDF.", 400

@app.route('/suggest')
def suggest():
    q = request.args.get('q', '')
    if len(q) < 3:
        return jsonify([])
    url = f"https://nominatim.openstreetmap.org/search?q={q}, Contra Costa County, CA&format=json&limit=5&addressdetails=1"
    headers = {'User-Agent': 'NewspaperApp/1.0'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        results = resp.json()
        suggestions = []
        for r in results:
            addr = r.get('display_name', '').split(',')
            if len(addr) >= 2:
                suggestions.append(addr[0].strip() + ', ' + addr[1].strip())
        return jsonify(suggestions)
    except:
        return jsonify([])

def geocode_address(address):
    headers = {'User-Agent': 'NewspaperApp/1.0'}
    query = address
    if "Contra Costa" not in query and " CA" not in query:
        query = f"{address}, {COUNTY}"
        
    url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print(f"Geocoding error for {address}: {e}")
    return None, None

def process_route_background(addresses_data):
    print("Background thread started...")
    
    # Prepare all addresses
    all_addresses = []
    
    start_lat, start_lon = geocode_address(START_ADDRESS)
    if start_lat:
        all_addresses.append({
            "address": START_ADDRESS,
            "newspapers": "",
            "lat": start_lat,
            "lon": start_lon,
            "city": START_ADDRESS.split(',')[-2].strip()
        })
        
    time.sleep(1)
        
    has_always = False
    for a in addresses_data:
        if a['address'].lower() == ALWAYS_INCLUDE_ADDRESS.split(',')[0].lower():
            has_always = True
            break
            
    if not has_always:
        always_lat, always_lon = geocode_address(ALWAYS_INCLUDE_ADDRESS)
        if always_lat:
            all_addresses.append({
                "address": ALWAYS_INCLUDE_ADDRESS,
                "newspapers": "",
                "lat": always_lat,
                "lon": always_lon,
                "city": ALWAYS_INCLUDE_ADDRESS.split(',')[-2].strip()
            })
        time.sleep(1)
        
    for item in addresses_data:
        lat = item.get('lat')
        lon = item.get('lon')
        if not lat or not lon:
            lat, lon = geocode_address(item['address'])
            time.sleep(1)
            
        if lat and lon:
            all_addresses.append({
                "address": item['address'],
                "newspapers": item.get('newspapers', ''),
                "lat": lat,
                "lon": lon,
                "city": item.get('city', '')
            })

    # Route optimization via OSRM Trip API
    distances_dict = {}
    if len(all_addresses) > 1:
        coords = ";".join([f"{item['lon']},{item['lat']}" for item in all_addresses])
        url = (
            f"https://router.project-osrm.org/trip/v1/driving/{coords}"
            f"?source=first&destination=any&roundtrip=false"
            f"&continue_straight=false&overview=full&geometries=geojson"
        )
        
        try:
            resp = requests.get(url, timeout=20)
            data = resp.json()
            if data.get("code") == "Ok":
                waypoints = data.get("waypoints", [])
                trips = data.get("trips", [])
                
                ordered_addresses = [None] * len(all_addresses)
                waypoint_to_idx = {}
                for wp in waypoints:
                    original_idx = wp['original_index']
                    new_idx = wp['waypoint_index']
                    ordered_addresses[new_idx] = all_addresses[original_idx]
                    waypoint_to_idx[new_idx] = original_idx
                    
                all_addresses = [x for x in ordered_addresses if x is not None]
                
                if trips and 'legs' in trips[0]:
                    legs = trips[0]['legs']
                    for i, leg in enumerate(legs):
                        if i < len(all_addresses) - 1:
                            dist_miles = leg.get('distance', 0) / 1609.34
                            all_addresses[i]['miles_to_next'] = f"{dist_miles:.1f}"
        except Exception as e:
            print(f"OSRM Routing error: {e}")

    # Sort same-street adjacent addresses numerically
    grouped = []
    i = 0
    while i < len(all_addresses):
        current = all_addresses[i]
        street_name = " ".join(current['address'].split(" ")[1:])
        
        group = [current]
        j = i + 1
        while j < len(all_addresses):
            nxt = all_addresses[j]
            if current['address'] == START_ADDRESS or nxt['address'] == START_ADDRESS:
                break
            nxt_street = " ".join(nxt['address'].split(" ")[1:])
            if nxt_street == street_name:
                group.append(nxt)
                j += 1
            else:
                break
                
        def extract_num(a):
            try:
                return int(a['address'].split(" ")[0])
            except:
                return 0
        group.sort(key=extract_num)
        
        grouped.extend(group)
        i = j
        
    all_addresses = grouped

    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = [
        "Chapter", "Media Link", "Media Credit", "Media Credit Link", 
        "Description", "Zoom", "Marker", "Marker Color", "Location", 
        "Latitude", "Longitude", "Overlay", "Overlay Transparency", 
        "GeoJSON Overlay", "GeoJSON Feature Properties", "Newspapers", "Maps Link", "Miles To Next"
    ]
    writer.writerow(headers)
    
    for idx, item in enumerate(all_addresses):
        addr = item['address']
        city = item.get('city') or 'CA'
        papers = item['newspapers']
        lat = item['lat']
        lon = item['lon']
        miles = item.get('miles_to_next', '')
        
        maps_link = f"https://www.google.com/maps/search/?api=1&query={addr.replace(' ', '+')}"
        color = "red" if addr == START_ADDRESS else "blue"
        
        chapter = f"{addr}, {city}" if city != 'CA' and city not in addr else f"{addr}, CA"
        if city in addr:
            chapter = addr
            
        row = [
            chapter, "", "Open in Maps", maps_link, "", "18", "Numbered", color, "",
            lat, lon, "", "", "", "", papers, maps_link, miles
        ]
        writer.writerow(row)
            
    csv_content = output.getvalue()
    upload_to_github(csv_content, "csv/Chapters.csv")
    
    found_count = len(all_addresses)
    not_found_count = len(addresses_data) - (found_count - 1) if found_count > 0 else 0
    if not_found_count < 0: not_found_count = 0
    meta = {"found": found_count, "not_found": not_found_count, "timestamp": datetime.now().isoformat()}
    upload_to_github(json.dumps(meta, indent=2), "csv/upload_meta.json")

def upload_to_github(content, file_path):
    if not GITHUB_TOKEN:
        print(f"No GITHUB_TOKEN found. Cannot upload {file_path} to GitHub.")
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                f.write(content)
        except:
            pass
        return
        
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    get_resp = requests.get(url, headers=headers)
    sha = None
    if get_resp.status_code == 200:
        sha = get_resp.json()['sha']
        
    data = {
        "message": f"Auto-update {file_path} from PDF upload {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": base64.b64encode(content.encode('utf-8')).decode('utf-8')
    }
    if sha:
        data['sha'] = sha
        
    put_resp = requests.put(url, headers=headers, json=data)
    if put_resp.status_code in [200, 201]:
        print(f"Successfully uploaded {file_path} to GitHub.")
    else:
        print(f"Failed to upload {file_path} to GitHub: {put_resp.status_code} {put_resp.text}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    data = request.json
    addresses = data.get('addresses', [])
    
    thread = threading.Thread(target=process_route_background, args=(addresses,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "success", "message": "Processing started. Chapters.csv will be updated on GitHub shortly."})

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('csv', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
