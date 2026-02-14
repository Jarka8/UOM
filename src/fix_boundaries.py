"""
Fix city boundaries using OpenStreetMap data.
This filters out areas outside the actual city limits.
"""

import glob
import pandas as pd
import requests
import json
from shapely.geometry import shape, Point
import os


def get_city_boundary_geojson(city_name):
    """
    Fetch actual city boundary from OpenStreetMap.
    Returns GeoJSON polygon of city limits.
    """
    # Nominatim API (OpenStreetMap)
    url = "https://nominatim.openstreetmap.org/search"
    
    city_queries = {
        'milan': 'Milano, Lombardia, Italia',
        'copenhagen': 'København, Danmark',
        'bologna': 'Bologna, Emilia-Romagna, Italia',
    }
    
    query = city_queries.get(city_name, city_name)
    
    params = {
        'q': query,
        'format': 'geojson',
        'polygon_geojson': 1,
        'limit': 1
    }
    
    headers = {
        'User-Agent': 'UrbanOpportunityMapper/1.0'
    }
    
    print(f"Fetching boundary for {city_name}...")
    response = requests.get(url, params=params, headers=headers)
    data = response.json()
    
    if not data.get('features'):
        raise ValueError(f"No boundary found for {city_name}")
    
    # Get the geometry
    geometry = data['features'][0]['geometry']
    
    # Save for reuse
    os.makedirs('data/boundaries', exist_ok=True)
    with open(f'data/boundaries/{city_name}_boundary.geojson', 'w') as f:
        json.dump(geometry, f)
    
    print(f"✓ Boundary saved: data/boundaries/{city_name}_boundary.geojson")
    
    return geometry


def load_city_boundary(city_name):
    """Load boundary from file or fetch if not exists."""
    filepath = f'data/boundaries/{city_name}_boundary.geojson'
    
    if os.path.exists(filepath):
        print(f"Loading existing boundary: {filepath}")
        with open(filepath, 'r') as f:
            geometry = json.load(f)
        return geometry
    else:
        return get_city_boundary_geojson(city_name)


def filter_analysis_to_city_boundary(analysis_df, city_name):
    """
    Filter analysis dataframe to only include points within city boundary.
    
    Args:
        analysis_df: DataFrame with center_lat, center_lng columns
        city_name: Name of city
        
    Returns:
        Filtered DataFrame with only points inside city
    """
    
    # Load boundary
    boundary_geom = load_city_boundary(city_name)
    boundary_polygon = shape(boundary_geom)
    
    print(f"\nFiltering {len(analysis_df)} grid cells to {city_name} boundary...")
    
    # Check each point
    inside_city = []
    for _, row in analysis_df.iterrows():
        point = Point(row['center_lng'], row['center_lat'])
        inside_city.append(boundary_polygon.contains(point))
    
    # Filter
    filtered_df = analysis_df[inside_city].copy()
    
    removed = len(analysis_df) - len(filtered_df)
    print(f"✓ Filtered to {len(filtered_df)} cells inside city")
    print(f"  Removed {removed} cells ({removed/len(analysis_df)*100:.1f}%) outside city limits")
    
    return filtered_df


def reprocess_all_analyses(city='milan'):
    """
    Reprocess all existing analysis files to filter to city boundary.
    This fixes the square boundary problem!
    """
    
    pattern = f'data/processed/{city}_*_analysis_*.csv'
    files = glob.glob(pattern)
    
    if not files:
        print(f"No analysis files found for {city}")
        return
    
    print(f"\n{'='*70}")
    print(f"REPROCESSING ANALYSES FOR {city.upper()}")
    print(f"{'='*70}")
    print(f"Found {len(files)} files to reprocess\n")
    
    for filepath in files:
        print(f"Processing: {filepath}")
        
        # Load
        df = pd.read_csv(filepath)
        original_count = len(df)
        
        # Filter to city boundary
        filtered_df = filter_analysis_to_city_boundary(df, city)
        
        # Save with _filtered suffix
        new_filepath = filepath.replace('_analysis_', '_analysis_filtered_')
        filtered_df.to_csv(new_filepath, index=False)
        
        print(f"✓ Saved: {new_filepath}")
        print(f"  {original_count} → {len(filtered_df)} cells\n")
    
    print(f"{'='*70}")
    print("COMPLETE!")
    print(f"{'='*70}")
    print("\nYour app will now use the filtered data.")
    print("The maps should look much better - only showing actual Milan!")


if __name__ == "__main__":
    import sys
    
    # Install required library
    try:
        from shapely.geometry import shape, Point
    except ImportError:
        print("Installing required library...")
        import subprocess
        subprocess.check_call(['pip', 'install', 'shapely', 'requests'])
        from shapely.geometry import shape, Point
    
    city = sys.argv[1] if len(sys.argv) > 1 else 'milan'
    
    reprocess_all_analyses(city)