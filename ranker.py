import numpy as np
import pandas as pd
import streamlit as st
import requests
import random
import json
import pickle
import os
import hashlib
from datetime import datetime
import folium
from streamlit_folium import st_folium
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse
import time
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

# Configuration
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1RQ0rQkQDdF16tb8UCYF_ai-dL5U_i4iIkpUQXBHv5kE/edit?usp=sharing"
ELO_DATA_FILE = "apartment_elo_data.pkl"
ELO_RANKINGS_CSV = "apartment_elo_rankings.csv"
GEOCODING_CACHE_FILE = "geocoding_cache.pkl"
INITIAL_ELO = 1000
K_FACTOR = 32

# Geocoding cache to avoid repeated API calls
GEOCODING_CACHE = {}

class ApartmentEloRanker:
    def __init__(self):
        self.apartments_df = None
        self.elo_scores = {}
        self.match_history = []
        
    def load_data(self):
        """Load apartment data from Google Sheets"""
        try:
            # Convert Google Sheets URL to CSV format
            csv_url = SPREADSHEET_URL.replace('/edit?usp=sharing', '/export?format=csv')
            self.apartments_df = pd.read_csv(csv_url)

            self.apartments_df = self.apartments_df[self.apartments_df["Link"] != "nan"]
            self.apartments_df = self.apartments_df[self.apartments_df["Link"] != ""]
            self.apartments_df = self.apartments_df[~self.apartments_df["Link"].isna()]
            
            # Load saved ELO data now that we have apartment data
            self.load_saved_data()
            
            # Initialize ELO scores for new apartments (preserving existing ones)
            for idx, row in self.apartments_df.iterrows():
                apt_id = self._get_apartment_id(row)
                if apt_id not in self.elo_scores:
                    self.elo_scores[apt_id] = INITIAL_ELO
                    
            return True
        except Exception as e:
            # Only show error if in Streamlit context
            try:
                st.error(f"Error loading data: {str(e)}")
            except:
                print(f"Error loading data: {str(e)}")
            return False
    
    def _get_apartment_id(self, row):
        """Generate unique ID for apartment based on link"""
        return hashlib.md5(row['Link'].encode()).hexdigest()
    
    def calculate_elo_change(self, winner_elo, loser_elo):
        """Calculate ELO rating changes"""
        expected_winner = 1 / (1 + 10**((loser_elo - winner_elo) / 400))
        expected_loser = 1 / (1 + 10**((winner_elo - loser_elo) / 400))
        
        winner_new = winner_elo + K_FACTOR * (1 - expected_winner)
        loser_new = loser_elo + K_FACTOR * (0 - expected_loser)
        
        return winner_new, loser_new
    
    def record_match(self, winner_idx, loser_idx):
        """Record a match result and update ELO scores"""
        winner_id = self._get_apartment_id(self.apartments_df.iloc[winner_idx])
        loser_id = self._get_apartment_id(self.apartments_df.iloc[loser_idx])
        
        winner_elo = self.elo_scores[winner_id]
        loser_elo = self.elo_scores[loser_id]
        
        new_winner_elo, new_loser_elo = self.calculate_elo_change(winner_elo, loser_elo)
        
        self.elo_scores[winner_id] = new_winner_elo
        self.elo_scores[loser_id] = new_loser_elo
        
        # Record match history
        self.match_history.append({
            'timestamp': datetime.now(),
            'winner_idx': winner_idx,
            'loser_idx': loser_idx,
            'winner_elo_before': winner_elo,
            'loser_elo_before': loser_elo,
            'winner_elo_after': new_winner_elo,
            'loser_elo_after': new_loser_elo
        })
        
        self.save_data()
    
    def get_random_pair(self):
        """Get two random apartments for comparison"""
        if len(self.apartments_df) < 2:
            return None, None
        
        indices = random.sample(range(len(self.apartments_df)), 2)
        return indices[0], indices[1]
    
    def get_active_learning_pair(self):
        """Get two apartments for comparison using active learning principles"""
        if len(self.apartments_df) < 2:
            return None, None
        
        # Get current ELO scores for all apartments
        apartment_elos = []
        for idx, row in self.apartments_df.iterrows():
            apt_id = self._get_apartment_id(row)
            elo = self.elo_scores.get(apt_id, INITIAL_ELO)
            apartment_elos.append((idx, elo))
        
        # Sort by ELO score
        apartment_elos.sort(key=lambda x: x[1], reverse=True)
        
        # Find the best pair with similar ELO scores
        best_pair = None
        min_elo_diff = float('inf')
        
        for i in range(len(apartment_elos)):
            for j in range(i + 1, len(apartment_elos)):
                idx1, elo1 = apartment_elos[i]
                idx2, elo2 = apartment_elos[j]
                
                # Calculate ELO difference
                elo_diff = abs(elo1 - elo2)
                
                # Check if this pair was recently matched
                if self._was_recently_matched(idx1, idx2):
                    continue
                
                # Prioritize smaller ELO differences (more uncertain outcomes)
                if elo_diff < min_elo_diff:
                    min_elo_diff = elo_diff
                    best_pair = (idx1, idx2)
        
        # If no good pair found (all were recently matched), fall back to random
        if best_pair is None:
            return self.get_random_pair()
        
        return best_pair
    
    def _was_recently_matched(self, idx1, idx2, recent_matches=5):
        """Check if two apartments were matched in the last N matches"""
        if len(self.match_history) < recent_matches:
            matches_to_check = self.match_history
        else:
            matches_to_check = self.match_history[-recent_matches:]
        
        for match in matches_to_check:
            if ((match['winner_idx'] == idx1 and match['loser_idx'] == idx2) or
                (match['winner_idx'] == idx2 and match['loser_idx'] == idx1)):
                return True
        return False
    
    def get_balanced_pair(self):
        """Get two apartments ensuring balanced coverage"""
        if len(self.apartments_df) < 2:
            return None, None
        
        # Count how many times each apartment has been in matches
        match_counts = {}
        for idx in range(len(self.apartments_df)):
            match_counts[idx] = 0
        
        for match in self.match_history:
            match_counts[match['winner_idx']] += 1
            match_counts[match['loser_idx']] += 1
        
        # Sort apartments by match count (ascending)
        sorted_apartments = sorted(match_counts.items(), key=lambda x: x[1])
        
        # Try to match the least-matched apartments
        for i in range(len(sorted_apartments)):
            for j in range(i + 1, len(sorted_apartments)):
                idx1, count1 = sorted_apartments[i]
                idx2, count2 = sorted_apartments[j]
                
                # If both have low match counts, use them
                if count1 <= 2 and count2 <= 2:
                    if not self._was_recently_matched(idx1, idx2):
                        return idx1, idx2
        
        # Fall back to active learning if no low-match pairs found
        return self.get_active_learning_pair()
    
    def get_smart_pair(self, strategy="active_learning"):
        """Get a smart pair using the specified strategy"""
        if strategy == "active_learning":
            return self.get_active_learning_pair()
        elif strategy == "balanced":
            return self.get_balanced_pair()
        else:
            return self.get_random_pair()
    
    def save_data(self):
        """Save ELO scores and match history"""
        data = {
            'elo_scores': self.elo_scores,
            'match_history': self.match_history
        }
        try:
            with open(ELO_DATA_FILE, 'wb') as f:
                pickle.dump(data, f)
            print(f"Successfully saved {len(self.elo_scores)} ELO scores and {len(self.match_history)} matches to {ELO_DATA_FILE}")
            
            # Also export rankings to CSV
            self.export_rankings_to_csv()
        except Exception as e:
            print(f"Error saving data: {str(e)}")
            # Only show error if in Streamlit context
            try:
                st.error(f"Error saving data: {str(e)}")
            except:
                pass
    
    def load_saved_data(self):
        """Load saved ELO scores and match history"""
        if os.path.exists(ELO_DATA_FILE):
            try:
                with open(ELO_DATA_FILE, 'rb') as f:
                    data = pickle.load(f)
                    self.elo_scores = data.get('elo_scores', {})
                    self.match_history = data.get('match_history', [])
                    
                # Debug info (only in non-Streamlit context for now)
                print(f"Successfully loaded {len(self.elo_scores)} ELO scores and {len(self.match_history)} matches from {ELO_DATA_FILE}")
                    
            except Exception as e:
                # Only show warning if in Streamlit context
                try:
                    st.warning(f"Could not load saved data: {str(e)}")
                except:
                    print(f"Could not load saved data: {str(e)}")
                # Reset to empty if loading fails
                self.elo_scores = {}
                self.match_history = []
        else:
            # No saved data file exists yet
            self.elo_scores = {}
            self.match_history = []
            print(f"No saved data file found at {ELO_DATA_FILE}, starting fresh")
    
    def get_rankings(self):
        """Get current rankings sorted by ELO"""
        rankings = []
        for idx, row in self.apartments_df.iterrows():
            apt_id = self._get_apartment_id(row)
            elo = self.elo_scores.get(apt_id, INITIAL_ELO)
            rankings.append({
                'rank': 0,  # Will be set after sorting
                'apartment': row,
                'elo': elo,
                'index': idx
            })
        
        rankings.sort(key=lambda x: x['elo'], reverse=True)
        for i, ranking in enumerate(rankings):
            ranking['rank'] = i + 1
            
        return rankings

    def export_rankings_to_csv(self):
        """Export current rankings with all apartment data to CSV"""
        try:
            rankings = self.get_rankings()
            
            # Create a list to store flattened data
            csv_data = []
            
            for ranking in rankings:
                # Create a row with rank, ELO, and all apartment data
                row_data = {
                    'Rank': ranking['rank'],
                    'ELO_Score': round(ranking['elo'], 2),
                    'Last_Updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Add all apartment columns
                for col_name, col_value in ranking['apartment'].items():
                    row_data[col_name] = col_value
                
                csv_data.append(row_data)
            
            # Convert to DataFrame and save to CSV
            df = pd.DataFrame(csv_data)
            df.to_csv(ELO_RANKINGS_CSV, index=False)
            
            return True
            
        except Exception as e:
            # Only show warning if in Streamlit context
            try:
                st.warning(f"Could not export rankings to CSV: {str(e)}")
            except:
                print(f"Could not export rankings to CSV: {str(e)}")
            return False

def extract_images_from_listing(url):
    """Extract images from apartment listing URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        images = []
        
        # For apartments.com
        if 'apartments.com' in url:
            # Look for various image selectors
            img_selectors = [
                'img[data-src*="jpg"]',
                'img[src*="jpg"]',
                '.carouselInner img',
                '.propertyImageContainer img',
                '.photoCarousel img'
            ]
            
            for selector in img_selectors:
                img_tags = soup.select(selector)
                for img in img_tags:
                    src = img.get('data-src') or img.get('src')
                    if src and 'jpg' in src and src not in images:
                        images.append(src)
                        
        return images[:6]  # Limit to 6 images
    except Exception as e:
        # Only show warning if in Streamlit context
        try:
            st.warning(f"Could not extract images from {url}: {str(e)}")
        except:
            pass
        return []

def load_geocoding_cache():
    """Load geocoding cache from file"""
    global GEOCODING_CACHE
    if os.path.exists(GEOCODING_CACHE_FILE):
        try:
            with open(GEOCODING_CACHE_FILE, 'rb') as f:
                GEOCODING_CACHE = pickle.load(f)
        except Exception as e:
            GEOCODING_CACHE = {}

def save_geocoding_cache():
    """Save geocoding cache to file"""
    try:
        with open(GEOCODING_CACHE_FILE, 'wb') as f:
            pickle.dump(GEOCODING_CACHE, f)
    except Exception as e:
        pass

def geocode_address(address):
    """Geocode an address to get lat/lon coordinates"""
    global GEOCODING_CACHE
    
    # Check cache first
    if address in GEOCODING_CACHE:
        return GEOCODING_CACHE[address]
    
    try:
        # Initialize geocoder (Nominatim is free and doesn't require API key)
        geolocator = Nominatim(user_agent="apartment_elo_ranker")
        
        # Try to geocode the address
        location = geolocator.geocode(address, timeout=10)
        
        if location:
            lat, lon = location.latitude, location.longitude
            # Cache the result
            GEOCODING_CACHE[address] = (lat, lon)
            save_geocoding_cache()
            return lat, lon
        else:
            # If geocoding fails, try with just the city and state
            # Extract city, state from address
            if "New York" in address or "NY" in address:
                # Default to NYC center for NY addresses
                lat, lon = 40.7128, -74.0060
            elif "Queens" in address:
                lat, lon = 40.7282, -73.7949
            elif "Brooklyn" in address:
                lat, lon = 40.6782, -73.9442
            elif "Manhattan" in address:
                lat, lon = 40.7831, -73.9712
            elif "Long Island City" in address:
                lat, lon = 40.7505, -73.9409
            else:
                # Default to NYC center
                lat, lon = 40.7128, -74.0060
            
            GEOCODING_CACHE[address] = (lat, lon)
            save_geocoding_cache()
            return lat, lon
            
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        # Fallback to NYC area based on address content
        if "Queens" in address:
            lat, lon = 40.7282, -73.7949
        elif "Brooklyn" in address:
            lat, lon = 40.6782, -73.9442
        elif "Manhattan" in address:
            lat, lon = 40.7831, -73.9712
        elif "Long Island City" in address:
            lat, lon = 40.7505, -73.9409
        else:
            lat, lon = 40.7128, -74.0060
        
        GEOCODING_CACHE[address] = (lat, lon)
        save_geocoding_cache()
        return lat, lon
    
    except Exception as e:
        # Final fallback to NYC center
        lat, lon = 40.7128, -74.0060
        GEOCODING_CACHE[address] = (lat, lon)
        save_geocoding_cache()
        return lat, lon

def create_map(address):
    """Create a map for the given address"""
    try:
        # Load geocoding cache
        load_geocoding_cache()
        
        # Get coordinates for the address
        lat, lon = geocode_address(address)
        
        # Create map centered on the address
        m = folium.Map(location=[lat, lon], zoom_start=15)
        
        # Add marker for the apartment
        folium.Marker(
            [lat, lon],
            popup=f"📍 {address}",
            tooltip=address,
            icon=folium.Icon(color='red', icon='home')
        ).add_to(m)
        
        # Add a circle to show the approximate area
        folium.Circle(
            [lat, lon],
            radius=200,
            popup=f"Area around {address}",
            color='blue',
            fill=True,
            fillColor='lightblue',
            fillOpacity=0.2
        ).add_to(m)
        
        return m
    except Exception as e:
        # Only show warning if in Streamlit context
        try:
            st.warning(f"Could not create map for {address}: {str(e)}")
        except:
            print(f"Could not create map for {address}: {str(e)}")
        return None

def display_apartment(apt_data, title):
    """Display apartment information in a column"""
    st.subheader(title)
    
    # Display basic info
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Cost:** ${apt_data['Cost']:,}")
        st.write(f"**Square Feet:** {apt_data['Square Foot (Guess)']} sq ft")
        st.write(f"**Niceness:** {apt_data['Niceness']}/10")
    
    with col2:
        st.write(f"**Bedrooms:** {apt_data['Bedrooms']}")
        st.write(f"**Bathrooms:** {apt_data['Bathrooms']}")
        st.write(f"**Start Date:** {apt_data['Start Date']}")
    
    st.write(f"**Address:** {apt_data['Addy']}")
    
    st.write(f"**Distance to Sparsh:** {apt_data['Dist Sparsh']} min")
    st.write(f"**Distance to Rishabh:** {apt_data['Dist Rishabh']} min")
    st.write(f"**Distance to Sena:** {apt_data['Dist Sena']} min")
    
    st.write(f"**Max Distance:** {apt_data['MAX Distance']} min")
    
    # Display link
    st.markdown(f"[View Listing]({apt_data['Link']})")
    
    # Display images
    with st.expander("View Images", expanded=True):
        images = extract_images_from_listing(apt_data['Link'])
        if images:
            cols = st.columns(min(3, len(images)))
            for i, img_url in enumerate(images[:3]):  # Show first 3 images
                with cols[i % 3]:
                    try:
                        st.image(img_url, use_container_width=True)
                    except:
                        st.write("Image could not be loaded")
        else:
            st.write("No images available")
    
    # Display map
    with st.expander("View Location", expanded=False):
        map_obj = create_map(apt_data['Addy'])
        if map_obj:
            st_folium(map_obj, width=400, height=300)

def main():
    st.set_page_config(
        page_title="Apartment ELO Ranker",
        page_icon="🏠",
        layout="wide"
    )
    
    st.title("🏠 Apartment ELO Ranking System")
    st.write("Compare apartments head-to-head to build your personalized rankings!")
    
    # Initialize ranker
    if 'ranker' not in st.session_state:
        st.session_state.ranker = ApartmentEloRanker()
        
    ranker = st.session_state.ranker
    
    # Load data
    if ranker.apartments_df is None:
        with st.spinner("Loading apartment data..."):
            if not ranker.load_data():
                st.error("Failed to load apartment data. Please check your connection.")
                return
    
    # Sidebar
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Choose a page:",
        ["Compare Apartments", "View Rankings", "Match History"]
    )
    
    # Matching Strategy Selection
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Matching Strategy")
    matching_strategy = st.sidebar.selectbox(
        "Choose matching strategy:",
        ["active_learning", "balanced", "random"],
        index=0,
        help="Active Learning: Match similar ELO apartments for maximum information. Balanced: Ensure all apartments get compared. Random: Traditional random matching."
    )
    
    # Show strategy info
    if matching_strategy == "active_learning":
        st.sidebar.info("🧠 **Active Learning**: Matches apartments with similar ELO scores for maximum information gain")
    elif matching_strategy == "balanced":
        st.sidebar.info("⚖️ **Balanced**: Ensures all apartments get compared roughly equally")
    else:
        st.sidebar.info("🎲 **Random**: Traditional random matching")
    
    # CSV Export button
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Data Export")
    if st.sidebar.button("Export Rankings to CSV", use_container_width=True):
        if ranker.export_rankings_to_csv():
            st.sidebar.success(f"Rankings exported to {ELO_RANKINGS_CSV}!")
        else:
            st.sidebar.error("Failed to export rankings.")
    
    st.sidebar.write(f"**Pickle file:** {ELO_DATA_FILE}")
    st.sidebar.write(f"**CSV file:** {ELO_RANKINGS_CSV}")
    
    # Debug info
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Debug Info")
    st.sidebar.write(f"**Total apartments:** {len(ranker.apartments_df) if ranker.apartments_df is not None else 0}")
    st.sidebar.write(f"**ELO scores loaded:** {len(ranker.elo_scores)}")
    st.sidebar.write(f"**Matches played:** {len(ranker.match_history)}")
    
    # Show match statistics
    if ranker.match_history:
        recent_matches = ranker.match_history[-10:]
        avg_elo_diff = sum(abs(match['winner_elo_before'] - match['loser_elo_before']) for match in recent_matches) / len(recent_matches)
        st.sidebar.write(f"**Avg ELO diff (last 10):** {avg_elo_diff:.0f}")
    
    if os.path.exists(ELO_DATA_FILE):
        mod_time = datetime.fromtimestamp(os.path.getmtime(ELO_DATA_FILE))
        st.sidebar.write(f"**Last saved:** {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.sidebar.write("**No saved data found**")
    
    if os.path.exists(ELO_RANKINGS_CSV):
        # Get file modification time
        mod_time = datetime.fromtimestamp(os.path.getmtime(ELO_RANKINGS_CSV))
        st.sidebar.write(f"**Last CSV export:** {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.sidebar.write("**CSV file:** Not yet created")
    
    if page == "Compare Apartments":
        st.header("🥊 Compare Two Apartments")
        
        # Add strategy explanation
        with st.expander("ℹ️ How Matching Strategies Work", expanded=False):
            st.markdown("""
            **🧠 Active Learning** (Recommended):
            - Matches apartments with similar ELO scores
            - Maximizes information gain from each comparison
            - Avoids predictable matchups (very high vs very low ELO)
            
            **⚖️ Balanced**:
            - Ensures all apartments get compared roughly equally
            - Good for comprehensive coverage
            - Prioritizes apartments that haven't been compared much
            
            **🎲 Random**:
            - Traditional random matching
            - No optimization, purely random selection
            - May waste comparisons on predictable matchups
            """)
        
        if len(ranker.apartments_df) < 2:
            st.error("Need at least 2 apartments to compare!")
            return
        
        # Get random pair
        if 'current_pair' not in st.session_state:
            st.session_state.current_pair = ranker.get_smart_pair(matching_strategy)
        
        idx1, idx2 = st.session_state.current_pair
        apt1 = ranker.apartments_df.iloc[idx1]
        apt2 = ranker.apartments_df.iloc[idx2]
        
        # Show match quality info
        current_elo_1 = ranker.elo_scores.get(ranker._get_apartment_id(apt1), INITIAL_ELO)
        current_elo_2 = ranker.elo_scores.get(ranker._get_apartment_id(apt2), INITIAL_ELO)
        elo_diff = abs(current_elo_1 - current_elo_2)
        
        st.info(f"🎯 **Match Quality**: ELO difference of {elo_diff:.0f} points using {matching_strategy.replace('_', ' ').title()} strategy")
        
        # Display apartments side by side
        col1, col2 = st.columns(2)
        
        with col1:
            display_apartment(apt1, "🏠 Apartment A")
            st.write(f"**Current ELO:** {current_elo_1:.0f}")
            
        with col2:
            display_apartment(apt2, "🏠 Apartment B")
            st.write(f"**Current ELO:** {current_elo_2:.0f}")
        
        # Voting buttons
        st.header("Which apartment do you prefer?")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("🏠 Choose Apartment A", use_container_width=True):
                ranker.record_match(idx1, idx2)
                st.success("Vote recorded! Apartment A wins!")
                st.session_state.current_pair = ranker.get_smart_pair(matching_strategy)
                time.sleep(1)
                st.rerun()
        
        with col2:
            if st.button("🔄 Skip This Comparison", use_container_width=True):
                st.session_state.current_pair = ranker.get_smart_pair(matching_strategy)
                st.rerun()
                
        with col3:
            if st.button("🏠 Choose Apartment B", use_container_width=True):
                ranker.record_match(idx2, idx1)
                st.success("Vote recorded! Apartment B wins!")
                st.session_state.current_pair = ranker.get_smart_pair(matching_strategy)
                time.sleep(1)
                st.rerun()
    
    elif page == "View Rankings":
        st.header("🏆 Current Rankings")
        
        rankings = ranker.get_rankings()
        
        # Add info about CSV export
        st.info(f"💡 Rankings are automatically saved to CSV after each match. You can also manually export using the sidebar button. Current file: `{ELO_RANKINGS_CSV}`")
        
        for ranking in rankings:
            with st.expander(f"#{ranking['rank']} - ELO: {ranking['elo']:.0f}"):
                apt = ranking['apartment']
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.write(f"**Address:** {apt['Addy']}")
                    st.write(f"**Cost:** ${apt['Cost']:,} | **Sq Ft:** {apt['Square Foot (Guess)']} | **Niceness:** {apt['Niceness']}/10")
                    st.write(f"**Bedrooms:** {apt['Bedrooms']} | **Bathrooms:** {apt['Bathrooms']}")
                    st.markdown(f"[View Listing]({apt['Link']})")
                
                with col2:
                    st.metric("ELO Rating", f"{ranking['elo']:.0f}")
    
    elif page == "Match History":
        st.header("📊 Match History")
        
        if ranker.match_history:
            st.write(f"Total matches played: {len(ranker.match_history)}")
            
            # Show recent matches
            recent_matches = ranker.match_history[-10:]  # Last 10 matches
            
            for i, match in enumerate(reversed(recent_matches)):
                with st.expander(f"Match {len(ranker.match_history) - i}"):
                    winner_apt = ranker.apartments_df.iloc[match['winner_idx']]
                    loser_apt = ranker.apartments_df.iloc[match['loser_idx']]
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**Winner:**")
                        st.write(f"Address: {winner_apt['Addy']}")
                        st.write(f"ELO: {match['winner_elo_before']:.0f} → {match['winner_elo_after']:.0f}")
                        
                    with col2:
                        st.write("**Loser:**")
                        st.write(f"Address: {loser_apt['Addy']}")
                        st.write(f"ELO: {match['loser_elo_before']:.0f} → {match['loser_elo_after']:.0f}")
        else:
            st.write("No matches played yet. Go to the Compare Apartments page to start!")

if __name__ == "__main__":
    main()