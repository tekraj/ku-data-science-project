import requests
# This suppresses the annoying "InsecureRequestWarning" messages in your console
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://www.nepalstock.com.np/api/nots/market/today-price"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nepalstock.com.np/"
}

# Add verify=False here
response = requests.get(url, headers=headers, verify=False)

if response.status_code == 200:
    print("Success!")
    data = response.json()
else:
    print(f"Status Code: {response.status_code}")