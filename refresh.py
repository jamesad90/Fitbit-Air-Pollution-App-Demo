# retrieve_data.py
import requests
import firebase_admin
from firebase_admin import credentials, firestore, exceptions
import os
from dotenv import load_dotenv
from datetime import date, timedelta, datetime
import time
import base64

# Firebase setup with error handling
try:
    cred = credentials.Certificate('breakthru-ee318-firebase-adminsdk-ots8p-370a215829.json')
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully.")
except FileNotFoundError:
    print("Firebase credentials file not found.")
    exit()
except exceptions.FirebaseError as e:
    print(f"Firebase initialization error: {e}")
    exit()

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TOKEN_URL = 'https://api.fitbit.com/oauth2/token'

def refresh_token(username, refresh_token):

    # Construct the authentication header
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    print(auth_header)
    headers = {
        'Authorization': 'Basic %s' % auth_header,
        'Content-Type' : 'application/x-www-form-urlencoded'
    }

        # Set up parameters for refresh request
    params = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }

    response = requests.post(TOKEN_URL, data=params, headers=headers)
    new_token = response.json()
    if 'errors' in new_token:
        print(f"Failed to refresh token for user {username}: {new_token}")
        return None
    print('New Token Retrieved:', new_token)

    expires_at = int(time.time()) + new_token['expires_in']

    db.collection('users').document(username).update({
        'access_token': new_token['access_token'],
        'refresh_token': new_token['refresh_token'],
        'expires_at': expires_at
    })
    print('User', username, 'New refresh token expires at:', datetime.utcfromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S'))
    return new_token['access_token']

def get_token(username):
    user_ref = db.collection('users').document(username)
    user_doc = user_ref.get()
    if user_doc.exists:
        return user_doc.to_dict()
    return None

def fetch_and_store_data(username):
    token_data = get_token(username)
    print(token_data)
    if not token_data:
        print(f"No token found for user {username}")
        return

    access_token = token_data['access_token']
    print('User', username, 'Refresh token expires at:', datetime.utcfromtimestamp(token_data['expires_at']).strftime('%Y-%m-%d %H:%M:%S'))
    refresh_token_expired = token_data['expires_at'] < time.time()
    if refresh_token_expired:
        access_token = refresh_token(username, token_data['refresh_token'])
    headers = {'Authorization': f'Bearer {access_token}'}
    
    start_date = '2024-07-10'
    end_date = '2024-07-13'
    user = "-"
    detail_level = '1min'
    
    endpoints_template = {
        'heartrate_daily_data': 'https://api.fitbit.com/1/user/{user}/activities/heart/date/{date}/{date}/{detail_level}.json',
        'steps_data': 'https://api.fitbit.com/1/user/{user}/activities/steps/date/{date}/{date}/{detail_level}.json',
        #'azm_data': 'https://api.fitbit.com/1/user/{user}/activities/active-zone-minutes/date/{date}/{date}/{detail_level}.json',
        'energy_data': 'https://api.fitbit.com/1/user/{user}/activities/calories/date/{date}/{date}/{detail_level}.json',
        'oxygen_saturation_data': 'https://api.fitbit.com/1/user/{user}/spo2/date/{date}/{date}/all.json',
        'hrv_data': 'https://api.fitbit.com/1/user/{user}/hrv/date/{date}/{date}/all.json',
        'respiratory_rate_data': 'https://api.fitbit.com/1/user/{user}/br/date/{date}/{date}/all.json',
        'sleep_data': 'https://api.fitbit.com/1.2/user/{user}/sleep/date/{date}/{date}.json',
        'electrocardiogram_data': f'https://api.fitbit.com/1/user/{user}/ecg/list.json?beforeDate={date}&offset=0&limit=10&sort=asc',
        'devices_data': 'https://api.fitbit.com/1/user/{user}/devices.json',
        'temperature_data': 'https://api.fitbit.com/1/user/-/temp/skin/date/{date}/{date}.json',
    }

    data = {}
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current_date <= end_date:
        date_str = current_date.isoformat()
        daily_data = {}
        
        for key, url_template in endpoints_template.items():
            url = url_template.format(user=user, date=date_str, detail_level=detail_level)
            response = requests.get(url, headers=headers)
            daily_data[key] = response.json()
        
        data[date_str] = daily_data
        current_date += timedelta(days=1)
    
    db.collection('user_data').document(username).set(data)
    
def get_usernames_from_db():
    users_ref = db.collection('users')
    docs = users_ref.stream()
    usernames = [doc.id for doc in docs]
    return usernames

if __name__ == '__main__':
    usernames = get_usernames_from_db()
    for username in usernames:
        print(username)
        fetch_and_store_data(username)
