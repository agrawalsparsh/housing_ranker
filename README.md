# 🏠 Apartment ELO Ranking System

A systematic way to rank apartments using head-to-head comparisons with ELO ratings, similar to chess rankings.

## Features

- **ELO Rating System**: All apartments start with 1000 ELO points
- **Head-to-Head Comparisons**: Compare two random apartments at a time
- **Rich Apartment Display**: 
  - View listing images automatically extracted from apartment URLs
  - See all apartment details (cost, size, bedrooms, etc.)
  - Interactive maps showing apartment locations
- **Persistent Rankings**: ELO scores are saved between sessions
- **Match History**: Track all your comparison decisions

## How It Works

1. **Data Source**: Reads apartment data from your Google Sheets
2. **Random Pairing**: Presents two random apartments for comparison
3. **ELO Calculation**: Uses standard ELO rating system to update scores based on wins/losses
4. **Visual Comparison**: Shows apartment images, details, and location maps
5. **Rankings**: View current rankings sorted by ELO score

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   streamlit run ranker.py
   ```

## Usage

1. **Compare Apartments**: Choose between two randomly selected apartments
2. **View Rankings**: See current ELO rankings of all apartments
3. **Match History**: Review your previous comparison decisions

## Data Format

The Google Sheets should have columns:
- Link: URL to apartment listing
- Cost: Monthly rent
- Square Foot (Guess): Estimated square footage
- Niceness: Your subjective rating (1-10)
- Bedrooms: Number of bedrooms
- Bathrooms: Number of bathrooms
- Addy: Full address
- Dist Sparsh, Dist Rishabh, Dist Sena: Distance to different people
- MAX Distance: Maximum distance value
- Start Date: When apartment becomes available

## Technical Details

- **ELO K-Factor**: 32 (standard for most applications)
- **Image Extraction**: Automatically scrapes images from apartments.com listings
- **Maps**: Uses Folium for interactive location maps with real geocoded coordinates
- **Geocoding**: Uses Nominatim (OpenStreetMap) for free address-to-coordinate conversion
- **Geocoding Cache**: Saves geocoded addresses locally to avoid repeated API calls
- **Data Persistence**: Saves ELO scores and match history locally using pickle

## Geocoding Options

### Default: Nominatim (Free)
- Uses OpenStreetMap's Nominatim service
- No API key required
- Good accuracy for most addresses
- Includes intelligent fallbacks for NYC neighborhoods

### Optional: Google Maps API (More Accurate)
For better geocoding accuracy:
1. Get a Google Maps API key from [Google Cloud Console](https://developers.google.com/maps/documentation/geocoding/get-api-key)
2. Edit `geocoding_config.py` and set your API key
3. Follow the instructions in the config file to switch to Google Maps geocoding

### Features:
- **Intelligent Caching**: Addresses are geocoded once and cached locally
- **Fallback Logic**: If geocoding fails, falls back to neighborhood-based coordinates
- **Enhanced Maps**: Shows apartment location with markers and area circles
- **NYC Optimized**: Special handling for NYC boroughs and neighborhoods

## Future Enhancements

- Advanced filtering options
- Export rankings to CSV
- Integration with more apartment listing sites
- Better geocoding for accurate maps 