"""
Data collection module for Urban Opportunity Mapper.

This module collects location data for businesses and services using the
Google Places API, following a systematic grid-based sampling approach
to ensure comprehensive coverage of the study area.

Methodology references:
- Grid-based sampling: Stopher & Stanley (transportation modeling)
- Service categories: Based on Moreno et al.'s 15-minute city framework
"""

import googlemaps
import pandas as pd
import os
import time
from dotenv import load_dotenv
from datetime import datetime
import json
import math

# Load environment variables
load_dotenv()
API_KEY = os.getenv("")
gmaps = googlemaps.Client(key="")

# Try to import OSM boundary functionality
try:
    from shapely.geometry import Point, Polygon
    import requests

    BOUNDARIES_AVAILABLE = True
    print("✓ Advanced boundary detection enabled")
except ImportError:
    BOUNDARIES_AVAILABLE = False
    print("⚠ Using approximate boundaries (install shapely for exact boundaries)")
    print("  Run: pip install shapely")


# ============================================================================
# CITY CONFIGURATIONS WITH ACCURATE BOUNDARIES
# ============================================================================

# Approximate boundaries (fallback if OSM not available)
CITY_BOUNDS_APPROX = {
    "milan": {
        "center": (45.4642, 9.1900),
        "bounds": {"north": 45.5350, "south": 45.3950, "east": 9.2800, "west": 9.0650},
        "osm_query": "Milano, Lombardia, Italia",
    },
    "copenhagen": {
        "center": (55.6761, 12.5683),
        "bounds": {
            "north": 55.7270,
            "south": 55.6150,
            "east": 12.6500,
            "west": 12.4530,
        },
        "osm_query": "København, Danmark",
    },
    "bologna": {
        "center": (44.4949, 11.3426),
        "bounds": {
            "north": 44.5450,
            "south": 44.4450,
            "east": 11.4000,
            "west": 11.2850,
        },
        "osm_query": "Bologna, Emilia-Romagna, Italia",
    },
    "rome": {
        "center": (41.9028, 12.4964),
        "bounds": {
            "north": 42.0500,
            "south": 41.7500,
            "east": 12.7000,
            "west": 12.3500,
        },
        "osm_query": "Roma, Lazio, Italia",
    },
    "turin": {
        "center": (45.0703, 7.6869),
        "bounds": {"north": 45.1300, "south": 45.0100, "east": 7.7500, "west": 7.6200},
        "osm_query": "Torino, Piemonte, Italia",
    },
}


# ============================================================================
# COMPREHENSIVE BUSINESS TYPE CATEGORIES
# ============================================================================

BUSINESS_TYPES = {
    # ESSENTIAL SERVICES (15-minute city core)
    "healthcare": [
        "pharmacy",
        "hospital",
        "doctor",
        "dentist",
        "physiotherapist",
    ],
    # FOOD & GROCERIES
    "food": [
        "supermarket",
        "grocery_or_supermarket",
        "bakery",
        "butcher",
        "liquor_store",
    ],
    # SOCIAL & COMMUNITY
    "social": [
        "cafe",
        "restaurant",
        "bar",
        "meal_takeaway",
    ],
    # RECREATION & WELLNESS
    "recreation": [
        "park",
        "gym",
        "spa",
        "stadium",
        "movie_theater",
    ],
    # EDUCATION & CULTURE
    "education": [
        "school",
        "library",
        "university",
        "book_store",
        "museum",
        "art_gallery",
    ],
    # SERVICES & RETAIL
    "services": [
        "bank",
        "atm",
        "post_office",
        "laundry",
        "hair_care",
        "beauty_salon",
        "clothing_store",
        "shoe_store",
        "electronics_store",
        "hardware_store",
        "florist",
        "pet_store",
    ],
    # TRANSPORTATION (for future transit accessibility analysis)
    "transport": [
        "transit_station",
        "subway_station",
        "bus_station",
        "train_station",
        "bicycle_store",
        "parking",
    ],
    # SUSTAINABILITY-FOCUSED (for environmental analysis)
    "sustainability": [
        "park",  # Green spaces
        "bicycle_store",
        "electric_vehicle_charging_station",
    ],
}

# Flatten to single list for easy iteration
ALL_BUSINESS_TYPES = [item for sublist in BUSINESS_TYPES.values() for item in sublist]

# Remove duplicates while preserving order
ALL_BUSINESS_TYPES = list(dict.fromkeys(ALL_BUSINESS_TYPES))

# Priority types for initial collection
PRIORITY_TYPES = [
    "pharmacy",
    "supermarket",
    "cafe",
    "park",
    "gym",
    "restaurant",
    "school",
    "bank",
    "transit_station",
]


# ============================================================================
# CITY BOUNDARY FUNCTIONS
# ============================================================================


def get_osm_boundary(city_name):
    """
    Fetch actual city boundary polygon from OpenStreetMap.

    This gives much more accurate city limits than rectangular boxes.
    Uses Nominatim (OSM's geocoding service) to get boundary polygon.

    Returns:
        Shapely Polygon object representing city boundary
    """
    if not BOUNDARIES_AVAILABLE:
        print("⚠ Shapely not available, using approximate boundaries")
        return None

    osm_query = CITY_BOUNDS_APPROX.get(city_name, {}).get("osm_query", city_name)

    try:
        print(f"Fetching boundary for {osm_query} from OpenStreetMap...")

        # Nominatim API endpoint
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": osm_query, "format": "json", "polygon_geojson": 1, "limit": 1}
        headers = {"User-Agent": "UrbanOpportunityMapper/1.0"}  # Required by Nominatim

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        if not data:
            print(f"⚠ No boundary found for {osm_query}")
            return None

        geojson = data[0].get("geojson")

        if not geojson:
            print(f"⚠ No geometry in response")
            return None

        # Convert GeoJSON to Shapely Polygon
        coords = geojson.get("coordinates", [])
        geom_type = geojson.get("type")

        if geom_type == "Polygon":
            # Simple polygon
            polygon = Polygon(coords[0])
        elif geom_type == "MultiPolygon":
            # Multiple polygons - use the largest one
            from shapely.geometry import MultiPolygon

            multi = MultiPolygon([Polygon(p[0]) for p in coords])
            polygon = max(multi.geoms, key=lambda p: p.area)
        else:
            print(f"⚠ Unexpected geometry type: {geom_type}")
            return None

        print(f"✓ Boundary loaded: {polygon.area:.6f} square degrees")
        return polygon

    except Exception as e:
        print(f"⚠ Error fetching OSM boundary: {e}")
        print("  Falling back to approximate boundaries")
        return None


def create_grid(city_name, grid_size_meters=500):
    """
    Create a grid of sample points covering the city.

    Now uses actual city boundaries if available, otherwise falls back
    to rectangular bounding box.

    Grid-based approach following Stopher & Stanley methodology for
    normalizing irregular urban boundaries and enabling city comparison.

    Args:
        city_name: Name of city (must be in CITY_BOUNDS_APPROX)
        grid_size_meters: Size of grid cells in meters (default: 500m)

    Returns:
        List of (lat, lng) tuples representing grid cell centers

    Note:
        500m grid provides optimal balance between resolution and
        computational efficiency for neighborhood-level analysis.
    """
    if city_name not in CITY_BOUNDS_APPROX:
        raise ValueError(
            f"City {city_name} not configured. Available: {list(CITY_BOUNDS_APPROX.keys())}"
        )

    city_config = CITY_BOUNDS_APPROX[city_name]
    bounds = city_config["bounds"]

    # Try to get actual boundary
    boundary_polygon = get_osm_boundary(city_name)

    # Create rectangular grid first
    lat_step = grid_size_meters / 111000  # 1 degree latitude ≈ 111km

    center_lat = (bounds["north"] + bounds["south"]) / 2
    lng_step = grid_size_meters / (111000 * abs(math.cos(math.radians(center_lat))))

    grid_points = []
    lat = bounds["south"]

    print(f"\nGenerating grid for {city_name}...")
    print(f"Grid size: {grid_size_meters}m × {grid_size_meters}m")

    while lat <= bounds["north"]:
        lng = bounds["west"]
        while lng <= bounds["east"]:
            grid_points.append((lat, lng))
            lng += lng_step
        lat += lat_step

    print(f"Initial grid: {len(grid_points)} points")

    # Filter to city boundary if available
    if boundary_polygon and BOUNDARIES_AVAILABLE:
        print("Filtering to actual city boundary...")
        filtered_points = []

        for lat, lng in grid_points:
            point = Point(lng, lat)  # Note: Shapely uses (lng, lat) order
            if boundary_polygon.contains(point):
                filtered_points.append((lat, lng))

        print(f"After boundary filter: {len(filtered_points)} points")
        print(
            f"Removed {len(grid_points) - len(filtered_points)} points outside city limits"
        )

        grid_points = filtered_points
    else:
        print(
            "Using rectangular boundary (install shapely + requests for exact boundaries)"
        )

    print(f"✓ Final grid: {len(grid_points)} sample points\n")

    return grid_points


# ============================================================================
# DATA COLLECTION FUNCTIONS
# ============================================================================


def collect_places_for_grid(grid_points, place_type, city_name, radius=500):
    """
    Collect all places of a given type within radius of each grid point.

    Uses systematic sampling to ensure comprehensive coverage while
    managing API quota efficiently.

    Args:
        grid_points: List of (lat, lng) tuples
        place_type: Google Places type (e.g., 'pharmacy')
        city_name: Name of city (for logging/saving)
        radius: Search radius in meters around each grid point

    Returns:
        DataFrame with all unique places found
    """
    all_places = []
    seen_place_ids = set()  # Avoid duplicates

    print(f"\n{'='*60}")
    print(f"Collecting {place_type} data for {city_name}")
    print(f"{'='*60}")
    print(f"Searching {len(grid_points)} grid points with {radius}m radius")
    print(f"Started at: {datetime.now().strftime('%H:%M:%S')}")

    errors = 0

    for i, (lat, lng) in enumerate(grid_points):
        # Rate limiting & progress
        if i > 0 and i % 10 == 0:
            print(
                f"Progress: {i}/{len(grid_points)} points ({i/len(grid_points)*100:.1f}%) | Found: {len(all_places)} unique places"
            )
            time.sleep(0.5)  # Be nice to the API

        try:
            # Search for places near this grid point
            result = gmaps.places_nearby(
                location=(lat, lng), radius=radius, type=place_type
            )

            # Process results
            if "results" in result:
                for place in result["results"]:
                    place_id = place.get("place_id")

                    # Skip if we've seen this place already
                    if place_id in seen_place_ids:
                        continue

                    seen_place_ids.add(place_id)

                    # Extract relevant data
                    place_data = {
                        "place_id": place_id,
                        "name": place.get("name"),
                        "type": place_type,
                        "lat": place["geometry"]["location"]["lat"],
                        "lng": place["geometry"]["location"]["lng"],
                        "rating": place.get("rating"),
                        "user_ratings_total": place.get("user_ratings_total"),
                        "price_level": place.get("price_level"),
                        "vicinity": place.get("vicinity"),
                        "types": ",".join(place.get("types", [])),
                        "business_status": place.get("business_status"),
                        "city": city_name,
                        "collected_at": datetime.now().isoformat(),
                    }

                    all_places.append(place_data)

        except Exception as e:
            errors += 1
            if errors <= 5:  # Only print first few errors
                print(f"⚠ Error at grid point ({lat:.4f}, {lng:.4f}): {e}")
            continue

    print(f"\n{'='*60}")
    print(f"COLLECTION COMPLETE - {place_type}")
    print(f"{'='*60}")
    print(f"✓ Found {len(all_places)} unique {place_type} locations")
    print(f"✓ Errors encountered: {errors}")
    print(f"✓ Completed at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    # Convert to DataFrame
    df = pd.DataFrame(all_places)

    # Add some basic statistics
    if len(df) > 0:
        print(f"Data quality stats:")
        print(
            f"  - With ratings: {df['rating'].notna().sum()} ({df['rating'].notna().sum()/len(df)*100:.1f}%)"
        )
        if df["rating"].notna().sum() > 0:
            print(f"  - Average rating: {df['rating'].mean():.2f}⭐")
        print(f"  - With price level: {df['price_level'].notna().sum()}")
        print()

    return df


def save_data(df, city_name, place_type):
    """Save collected data to CSV."""
    os.makedirs("data/raw", exist_ok=True)
    filename = (
        f"data/raw/{city_name}_{place_type}_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    df.to_csv(filename, index=False)
    print(f"✓ Saved to {filename}\n")
    return filename


def collect_city_data(city_name, business_types=None, grid_size=500):
    """
    Main function to collect all data for a city.

    Example usage:
        # Collect priority types for Milan
        collect_city_data('milan', PRIORITY_TYPES)

        # Collect everything for Milan (expensive!)
        collect_city_data('milan', ALL_BUSINESS_TYPES)

        # Collect specific types
        collect_city_data('milan', ['pharmacy', 'cafe', 'supermarket'])
    """
    if business_types is None:
        business_types = PRIORITY_TYPES

    if city_name not in CITY_BOUNDS_APPROX:
        raise ValueError(
            f"City {city_name} not configured. Available: {list(CITY_BOUNDS_APPROX.keys())}"
        )

    # Create grid with accurate boundaries
    print(f"\n{'='*70}")
    print(f"STARTING DATA COLLECTION FOR {city_name.upper()}")
    print(f"{'='*70}")
    print(f"Business types to collect: {len(business_types)}")
    print(f"Types: {', '.join(business_types)}")

    grid = create_grid(city_name, grid_size)

    # Estimate API calls and cost
    estimated_calls = len(grid) * len(business_types)
    estimated_cost_eur = estimated_calls * 0.017  # Approximate cost per call

    print(f"\n{'='*70}")
    print(f"COST ESTIMATE")
    print(f"{'='*70}")
    print(f"Grid points: {len(grid)}")
    print(f"Business types: {len(business_types)}")
    print(f"Estimated API calls: {estimated_calls}")
    print(f"Estimated cost: €{estimated_cost_eur:.2f}")
    print(f"{'='*70}\n")

    # Ask for confirmation if expensive
    if estimated_cost_eur > 20:
        response = input(
            f"⚠ This will cost approximately €{estimated_cost_eur:.2f}. Continue? (yes/no): "
        )
        if response.lower() != "yes":
            print("Collection cancelled.")
            return None

    # Collect data for each business type
    results_summary = {}

    start_time = datetime.now()

    for idx, biz_type in enumerate(business_types, 1):
        print(f"\n{'='*70}")
        print(f"TYPE {idx}/{len(business_types)}: {biz_type.upper()}")
        print(f"{'='*70}")

        df = collect_places_for_grid(grid, biz_type, city_name)

        if len(df) > 0:
            filename = save_data(df, city_name, biz_type)
            results_summary[biz_type] = {
                "count": len(df),
                "file": filename,
                "with_ratings": int(df["rating"].notna().sum()),
                "avg_rating": (
                    float(df["rating"].mean())
                    if df["rating"].notna().sum() > 0
                    else None
                ),
            }
        else:
            print(f"⚠ No {biz_type} locations found")
            results_summary[biz_type] = {"count": 0, "file": None}

        # Small delay between types to be respectful to API
        if idx < len(business_types):
            time.sleep(2)

    end_time = datetime.now()
    duration = end_time - start_time

    # Print final summary
    print(f"\n{'='*70}")
    print(f"COLLECTION COMPLETE - {city_name.upper()}")
    print(f"{'='*70}")
    print(f"Total time: {duration}")
    print(f"{'='*70}")

    # Summary table
    print(
        f"\n{'Business Type':<25} {'Count':>8} {'With Ratings':>15} {'Avg Rating':>12}"
    )
    print(f"{'-'*70}")

    total_places = 0
    for biz_type, info in results_summary.items():
        count = info["count"]
        total_places += count
        ratings = info.get("with_ratings", 0)
        avg_rating = info.get("avg_rating")

        rating_str = f"{avg_rating:.2f}⭐" if avg_rating else "N/A"

        print(f"{biz_type:<25} {count:>8} {ratings:>15} {rating_str:>12}")

    print(f"{'-'*70}")
    print(f"{'TOTAL':<25} {total_places:>8}")
    print(f"{'='*70}\n")

    # Save summary as JSON
    summary_file = f"data/raw/{city_name}_collection_summary_{datetime.now().strftime('%Y%m%d')}.json"
    with open(summary_file, "w") as f:
        json.dump(
            {
                "city": city_name,
                "collection_date": datetime.now().isoformat(),
                "duration_seconds": duration.total_seconds(),
                "business_types": results_summary,
                "total_places": total_places,
                "grid_size_meters": grid_size,
                "grid_points": len(grid),
            },
            f,
            indent=2,
        )

    print(f"✓ Summary saved to {summary_file}")

    return results_summary


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def test_api_connection():
    """
    Test that your API key works before running full collection.
    This only makes 1 API call to verify setup.
    """
    print("Testing API connection...")

    try:
        # Search for pharmacies near Milan center
        result = gmaps.places_nearby(
            location=CITY_BOUNDS_APPROX["milan"]["center"], radius=1000, type="pharmacy"
        )

        if "results" in result and len(result["results"]) > 0:
            print("✓ API connection successful!")
            print(f"✓ Found {len(result['results'])} pharmacies near Milan center")
            print(f"✓ Example: {result['results'][0]['name']}")
            return True
        else:
            print("⚠ API connected but no results returned")
            return False

    except Exception as e:
        print(f"✗ API connection failed: {e}")
        print("\nCheck:")
        print("1. Is your API key in .env file?")
        print("2. Is Places API enabled in Google Cloud Console?")
        print("3. Is billing enabled?")
        return False


def list_available_data(city_name=None):
    """
    List all data files that have been collected.
    Useful to see what you already have before collecting more.
    """
    data_dir = "data/raw"

    if not os.path.exists(data_dir):
        print("No data directory found. Run collection first.")
        return

    files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]

    if city_name:
        files = [f for f in files if f.startswith(city_name + "_")]

    if not files:
        print(f"No data found{' for ' + city_name if city_name else ''}")
        return

    print(f"\n{'='*70}")
    print(f"AVAILABLE DATA{' - ' + city_name.upper() if city_name else ''}")
    print(f"{'='*70}")

    by_city = {}
    for file in files:
        parts = file.replace(".csv", "").split("_")
        if len(parts) >= 3:
            city = parts[0]
            biz_type = parts[1]
            date = parts[2] if len(parts) > 2 else "unknown"

            if city not in by_city:
                by_city[city] = []

            # Get file size
            file_path = os.path.join(data_dir, file)
            df = pd.read_csv(file_path)

            by_city[city].append(
                {"type": biz_type, "count": len(df), "date": date, "file": file}
            )

    for city, data_list in by_city.items():
        print(f"\n{city.upper()}:")
        print(f"  {'Type':<20} {'Count':>8} {'Date':>12}")
        print(f"  {'-'*45}")
        for item in sorted(data_list, key=lambda x: x["type"]):
            print(f"  {item['type']:<20} {item['count']:>8} {item['date']:>12}")

    print(f"\n{'='*70}\n")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("URBAN OPPORTUNITY MAPPER - DATA COLLECTION")
    print(f"{'='*70}\n")

    # Test API first
    if not test_api_connection():
        print("\n✗ Please fix API setup before continuing")
        exit(1)

    print(f"\n{'='*70}")
    print("READY TO COLLECT DATA")
    print(f"{'='*70}\n")

    # Show what data we already have
    print("Checking for existing data...\n")
    list_available_data()

    # Interactive menu
    print("What would you like to do?")
    print()
    print(
        "1. Collect PRIORITY types for Milan (pharmacy, supermarket, cafe, park, etc.)"
    )
    print("2. Collect ALL types for Milan (comprehensive, expensive ~€100)")
    print("3. Collect specific types for Milan")
    print("4. Collect priority types for Copenhagen")
    print("5. Collect priority types for another city (Bologna, Rome, Turin)")
    print("6. List available data")
    print("7. Exit")
    print()

    choice = input("Enter choice (1-7): ").strip()

    if choice == "1":
        print("\nCollecting PRIORITY types for Milan...")
        print(f"Types: {', '.join(PRIORITY_TYPES)}")
        collect_city_data("milan", PRIORITY_TYPES)

    elif choice == "2":
        print("\n⚠ WARNING: This will collect ALL business types!")
        print(f"Total types: {len(ALL_BUSINESS_TYPES)}")
        print(f"Estimated cost: ~€80-100")
        confirm = input("Are you sure? (type 'YES' to confirm): ")
        if confirm == "YES":
            collect_city_data("milan", ALL_BUSINESS_TYPES)
        else:
            print("Cancelled.")

    elif choice == "3":
        print("\nAvailable categories:")
        for idx, (category, types) in enumerate(BUSINESS_TYPES.items(), 1):
            print(
                f"{idx}. {category}: {', '.join(types[:3])}{'...' if len(types) > 3 else ''}"
            )

        print("\nEnter business types separated by commas")
        print("Example: pharmacy,cafe,supermarket,park")
        types_input = input("\nTypes: ").strip()

        selected_types = [t.strip() for t in types_input.split(",")]

        print(f"\nWill collect: {', '.join(selected_types)}")
        confirm = input("Continue? (y/n): ")

        if confirm.lower() == "y":
            collect_city_data("milan", selected_types)

    elif choice == "4":
        print("\nCollecting PRIORITY types for Copenhagen...")
        collect_city_data("copenhagen", PRIORITY_TYPES)

    elif choice == "5":
        print("\nAvailable cities:")
        cities = [
            c for c in CITY_BOUNDS_APPROX.keys() if c not in ["milan", "copenhagen"]
        ]
        for idx, city in enumerate(cities, 1):
            print(f"{idx}. {city.title()}")

        city_choice = input("\nEnter city name: ").strip().lower()

        if city_choice in CITY_BOUNDS_APPROX:
            collect_city_data(city_choice, PRIORITY_TYPES)
        else:
            print(f"Unknown city: {city_choice}")

    elif choice == "6":
        city = input("City name (or press Enter for all): ").strip() or None
        list_available_data(city)

    elif choice == "7":
        print("Goodbye!")

    else:
        print("Invalid choice")
