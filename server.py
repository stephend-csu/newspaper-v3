import os
import threading
import time
import requests
import csv
import io
import pypdf
import base64
from flask import Flask, request, render_template, jsonify
from datetime import datetime

app = Flask(__name__)

# Constants
COUNTY = "Contra Costa County, CA"
START_ADDRESS = "923 Pacific Ct, Walnut Creek, CA"
GITHUB_REPO = "stephend-csu/newspaper-app-v2"
# Note: For production on Render, GITHUB_TOKEN should be set as an environment variable
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
            
        # If line starts with a number, it's likely a house number line
        parts = line.split()
        if parts[0].isdigit() and current_street:
            house_num = parts[0]
            if len(parts) > 1:
                newspaper = parts[1]
                # Combine address
                full_address = f"{house_num} {current_street.title()}"
                if full_address not in addresses:
                    addresses[full_address] = set()
                addresses[full_address].add(newspaper)
        else:
            # Might be a street name (e.g. PERRA WAY)
            # Ignoring "Route:..." or purely numeric/single word weird lines
            if "Route:" not in line and len(line) > 3:
                current_street = line
                
    result = []
    for addr, papers in addresses.items():
        result.append({
            "address": addr,
            "newspapers": " ".join(sorted(list(papers)))
        })
    return result

def geocode_address(address):
    # Nominatim requires a user agent
    headers = {'User-Agent': 'NewspaperApp/1.0'}
    
    # Try with Contra Costa County if not already there
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
    found_addresses = []
    not_found = []
    
    # Geocode start address
    start_lat, start_lon = geocode_address(START_ADDRESS)
    if not start_lat:
        print("Failed to geocode start address!")
        return
        
    found_addresses.append({
        "address": START_ADDRESS,
        "newspapers": "",
        "lat": start_lat,
        "lon": start_lon,
        "is_start": True
    })
    
    # Geocode all from PDF
    for item in addresses_data:
        addr = item['address']
        papers = item['newspapers']
        lat, lon = geocode_address(addr)
        
        if lat and lon:
            found_addresses.append({
                "address": addr,
                "newspapers": papers,
                "lat": lat,
                "lon": lon,
                "is_start": False
            })
        else:
            not_found.append(item)
            
        time.sleep(1) # respect Nominatim rate limits (1 req/sec)

    # Reorder using OSRM
    if len(found_addresses) > 1:
        # Build coordinates string for OSRM: lon,lat;lon,lat...
        coords = ";".join([f"{item['lon']},{item['lat']}" for item in found_addresses])
        
        url = (
            f"https://router.project-osrm.org/trip/v1/driving/{coords}"
            f"?source=first&destination=any&roundtrip=false"
            f"&continue_straight=false&overview=simplified"
        )
        
        try:
            resp = requests.get(url, timeout=20)
            data = resp.json()
            if data.get("code") == "Ok":
                waypoints = data.get("waypoints", [])
                
                # waypoints have waypoint_index mapping to our original list
                # Sort found_addresses based on waypoint_index
                ordered_addresses = [None] * len(found_addresses)
                for wp in waypoints:
                    original_idx = wp['original_index']
                    new_idx = wp['waypoint_index']
                    ordered_addresses[new_idx] = found_addresses[original_idx]
                
                # Overwrite found_addresses with ordered list
                found_addresses = [x for x in ordered_addresses if x is not None]
        except Exception as e:
            print(f"OSRM Routing error: {e}")
            # If it fails, we just keep the unordered list

    # Sort same-street addresses sequentially numerically
    # The routing usually groups them, but let's strictly sort if they are adjacent
    # (Since we used nearest neighbor, they might be slightly out of order on the same street)
    # Actually, a simple grouping approach:
    grouped = []
    i = 0
    while i < len(found_addresses):
        current = found_addresses[i]
        street_name = " ".join(current['address'].split(" ")[1:])
        
        # Gather all adjacent addresses on the same street
        group = [current]
        j = i + 1
        while j < len(found_addresses):
            nxt = found_addresses[j]
            if nxt['is_start']:
                break
            nxt_street = " ".join(nxt['address'].split(" ")[1:])
            if nxt_street == street_name:
                group.append(nxt)
                j += 1
            else:
                break
                
        # Sort group by house number
        def extract_num(a):
            try:
                return int(a['address'].split(" ")[0])
            except:
                return 0
        group.sort(key=extract_num)
        
        grouped.extend(group)
        i = j
        
    found_addresses = grouped

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = [
        "Chapter", "Media Link", "Media Credit", "Media Credit Link", 
        "Description", "Zoom", "Marker", "Marker Color", "Location", 
        "Latitude", "Longitude", "Overlay", "Overlay Transparency", 
        "GeoJSON Overlay", "GeoJSON Feature Properties", "Newspapers", "Maps Link"
    ]
    writer.writerow(headers)
    
    for idx, item in enumerate(found_addresses, start=2):
        addr = item['address']
        desc = "Start Address" if item.get('is_start') else ""
        papers = item['newspapers']
        lat = item['lat']
        lon = item['lon']
        
        # User requested a literal https link (they provided the formula as an example of what they used to do)
        maps_link = f"https://www.google.com/maps/search/?api=1&query={addr.replace(' ', '+')}"
        
        color = "red" if item.get('is_start') else "blue"
        
        row = [
            f"{addr}, CA" if ", CA" not in addr else addr,
            "", "Open in Maps", maps_link, desc, "18", "Numbered", color, "",
            lat, lon, "", "", "", "", papers, maps_link
        ]
        writer.writerow(row)
        
    # Append Not Found addresses
    if not_found:
        writer.writerow([]) # Blank row
        for item in not_found:
            addr = item['address']
            papers = item['newspapers']
            row = [
                f"{addr} (NOT FOUND)", "", "", "", "", "", "Hidden", "", "",
                "", "", "", "", "", "", papers, ""
            ]
            writer.writerow(row)
            
    csv_content = output.getvalue()
    
    # Upload to GitHub
    upload_to_github(csv_content)

def upload_to_github(csv_content):
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN found. Cannot upload to GitHub.")
        # Fallback to local save if possible
        try:
            with open("csv/Chapters.csv", "w", newline="", encoding="utf-8") as f:
                f.write(csv_content)
        except:
            pass
        return
        
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/csv/Chapters.csv"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Get current SHA
    get_resp = requests.get(url, headers=headers)
    sha = None
    if get_resp.status_code == 200:
        sha = get_resp.json()['sha']
        
    data = {
        "message": f"Auto-update Chapters.csv from PDF upload {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
    }
    if sha:
        data['sha'] = sha
        
    put_resp = requests.put(url, headers=headers, json=data)
    if put_resp.status_code in [200, 201]:
        print("Successfully uploaded to GitHub.")
    else:
        print(f"Failed to upload to GitHub: {put_resp.status_code} {put_resp.text}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'pdf_file' not in request.files:
        return "No file uploaded", 400
        
    file = request.files['pdf_file']
    if file.filename == '':
        return "No file selected", 400
        
    if file and file.filename.endswith('.pdf'):
        addresses = extract_addresses_from_pdf(file.stream)
        return render_template('review.html', addresses=addresses)
        
    return "Invalid file format. Please upload a PDF.", 400

@app.route('/process', methods=['POST'])
def process():
    data = request.json
    addresses = data.get('addresses', [])
    
    # Kick off background thread
    thread = threading.Thread(target=process_route_background, args=(addresses,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "success", "message": "Processing started in background. Chapters.csv will be updated on GitHub soon."})

if __name__ == '__main__':
    # Ensure templates folder exists
    os.makedirs('templates', exist_ok=True)
    os.makedirs('csv', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
