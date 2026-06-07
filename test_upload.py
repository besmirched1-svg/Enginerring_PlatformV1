import requests
import os

url = 'http://127.0.0.1:8000/upload'
files = {'files': open('test_template.scad', 'rb')}
try:
    response = requests.post(url, files=files)
    print(f'Status Code: {response.status_code}')
    print(f'Response: {response.json()}')
except Exception as e:
    print(f'Error: {e}')
