
from flask import Flask, render_template, request, redirect, url_for
from requests_oauthlib import OAuth2Session
import secrets
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, exceptions
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
import numpy as np
from datetime import datetime, timedelta
#from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

matplotlib.use('Agg')
# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)
# login_manager = LoginManager()
# login_manager.init_app(app)
# login_manager.login_view = 'login'  
# Initialize Firebase
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
# Fitbit OAuth configuration
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
#REDIRECT_URI = 'https://breakthru-ee318.nw.r.appspot.com/callback'
REDIRECT_URI = 'https://localhost:5000/callback'
AUTHORIZATION_BASE_URL = 'https://www.fitbit.com/oauth2/authorize'
TOKEN_URL = 'https://api.fitbit.com/oauth2/token'
SCOPE = ['profile', 'settings', 'activity', 'heartrate', 'oxygen_saturation', 'temperature', 'respiratory_rate', 'sleep', 'electrocardiogram']

# Helper function to save token to Firestore
def save_token(user_id, token):
    db.collection('users').document(user_id).set({
        'access_token': token['access_token'],
        'refresh_token': token['refresh_token'],
        'expires_at': token['expires_at']
    })

# Function to fetch user data from Firestore
def get_user_data(username):
    try:
        user_data_ref = db.collection('user_data').document(username)
        user_data_doc = user_data_ref.get()
        if user_data_doc.exists:
            return user_data_doc.to_dict()
        else:
            return None
    except Exception as e:
        print(f"Error fetching user data: {e}")
        return None

# Function to fetch all user data
def get_all_user_data():
    users_ref = db.collection('user_data').stream()
    user_data_list = []

    for user_doc in users_ref:
        username = user_doc.id
        user_data = user_doc.to_dict()
        datasets = {}

        for dataset_name, dataset in user_data.items():
            if isinstance(dataset, dict):  # Check if it's a dataset collection
                for dataset_key, dataset_value in dataset.items():
                    if dataset_key not in datasets:
                        datasets[dataset_key] = []
                    datasets[dataset_key].append(dataset_value)

        user_data_list.append({
            'username': username,
            'datasets': datasets
        })

    return user_data_list

# Route to render Fitbit authorization page
@app.route('/')
def index():
    fitbit = OAuth2Session(CLIENT_ID, scope=SCOPE, redirect_uri=REDIRECT_URI)
    authorization_url, _ = fitbit.authorization_url(AUTHORIZATION_BASE_URL)
    return render_template('auth_index.html', fitbit_auth_url=authorization_url)

# Callback route to handle OAuth callback from Fitbit
@app.route('/callback')
def callback():
    fitbit = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    token = fitbit.fetch_token(
        TOKEN_URL,
        authorization_response=request.url,
        client_secret=CLIENT_SECRET
    )
    user_id = token.get('user_id')
    if not user_id:
        return "User ID not found in token response. Authorization failed."
    
    save_token(user_id, token)
    return redirect(url_for('.success'))

# Success route after authentication
@app.route('/success')
def success():
    return render_template('success.html')

# Route to display user selection page
@app.route('/display_users')
def display_users():
    user_data_list = get_all_user_data()
    return render_template('user_selection.html', user_data_list=user_data_list)

@app.route('/display_user_data')
def display_user_data():
    username = request.args.get('username')
    user_data = get_user_data(username)
    
    if not user_data:
        return f"User data not found for username: {username}"
    
    hypnogram_imgs = []
    sleep_data = user_data.get('sleep_data', [])
    
    # Process sleep data into stages if available
    if sleep_data:
        all_night_stages = process_sleep_data(sleep_data)
        for reading in all_night_stages:
            date_str = reading['dateOfSleep']
            hypnogram_img, stage_durations = plot_hypnogram_for_day(reading)
            hypnogram_imgs.append((date_str, hypnogram_img, stage_durations))
    
    ecg_readings = user_data.get('electrocardiogram_data', {}).get('ecgReadings', [])
    
    # Generate a plot for each ECG reading if available
    if ecg_readings:
        for reading in ecg_readings:
            # Create a plot
            plt.figure()
            plt.plot(reading['waveformSamples'])
            plt.title('ECG Waveform')
            
            # Save it to a BytesIO object
            buf = BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            
            # Create a base64 string
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            reading['waveformPlot'] = img_base64
            
            plt.close()
    
    return render_template('display_user_data.html', username=username, health_data=user_data, hypnogram_imgs=hypnogram_imgs)



def process_sleep_data(sleep_data):
    all_night_stages = []

    for night in sleep_data['sleep']:
        if 'levels' in night and 'data' in night['levels']:
            stages = {'dateOfSleep': night['dateOfSleep'], 'data': []}

            for entry in night['levels']['data']:
                stage = entry['level']
                start_time = datetime.strptime(entry['dateTime'], '%Y-%m-%dT%H:%M:%S.%f')
                duration = entry['seconds']
                end_time = start_time + timedelta(seconds=duration)

                stages['data'].append((stage, start_time, end_time))

            all_night_stages.append(stages)
    
    return all_night_stages


def plot_hypnogram_for_day(night_stages):
    stage_map = {'wake': 0, "rem": 1, "light": 2, "deep": 3}
    stage_colors = {'wake': '#dddddd', 'rem': '#009879', 'light': 'blue', 'deep': '#ff9f43'}
    stage_durations = {'wake': 0, "rem": 0, "light": 0, "deep": 0}
    
    plt.figure(figsize=(6, 3))
    
    for stage, start_time, end_time in night_stages['data']:
        if stage in stage_map:
            duration = (end_time - start_time).total_seconds() / 60  # Duration in minutes
            stage_durations[stage] += duration
            
            plt.plot([start_time, end_time], [stage_map[stage], stage_map[stage]], color=stage_colors[stage], linewidth=10)

    plt.yticks([0, 1, 2, 3], ['Wake', 'REM', 'Light', 'Deep'])
    plt.title('Hypnogram')
    plt.xlabel('Time')
    plt.tight_layout()

    # Save plot to a BytesIO object
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)

    # Encode plot image as base64 for embedding in HTML
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()

    return img_base64, stage_durations


if __name__ == '__main__':
    app.run(debug=True, ssl_context = 'adhoc')