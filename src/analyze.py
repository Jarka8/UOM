"""
Analysis module for Urban Opportunity Mapper.

Implements Two-Step Floating Catchment Area (2SFCA) methodology
(Langford & Higgs, 2006) to identify service accessibility patterns
and business opportunities.
"""

import os
import pandas as pd
import numpy as np
from geopy.distance import geodesic
from datetime import datetime
from glob import glob


def load_data(city, business_type):
    """Load the most recent data file for a city and business type."""
    data_dir = "data/raw"

    # Find most recent file
    pattern = f"{city}_{business_type}_*.csv"
    files = [f for f in os.listdir(data_dir) if f.startswith(f"{city}_{business_type}_")]

    if not files:
        raise FileNotFoundError(f"No data found for {city} {business_type}")

    latest_file = sorted(files)[-1]  # Most recent by date
    filepath = os.path.join(data_dir, latest_file)

    print(f"Loading: {filepath}")
    df = pd.read_csv(filepath)
    print(f"✓ Loaded {len(df)} {business_type} locations")

    return df


def create_analysis_grid(bounds, grid_size_km=0.5):
    """
    Create grid cells for analysis.

    Following Stopher & Stanley methodology, we use 500m × 500m cells
    (0.5km) as optimal resolution for neighborhood-level analysis.

    Args:
        bounds: Dict with 'north', 'south', 'east', 'west'
        grid_size_km: Grid cell size in kilometers

    Returns:
        DataFrame with grid cell centers and metadata
    """
    # Convert grid size to degrees (approximate)
    lat_step = grid_size_km / 111  # 1 degree lat ≈ 111km

    center_lat = (bounds["north"] + bounds["south"]) / 2
    lng_step = grid_size_km / (111 * np.cos(np.radians(center_lat)))

    grid_cells = []
    cell_id = 0

    lat = bounds["south"]
    while lat <= bounds["north"]:
        lng = bounds["west"]
        while lng <= bounds["east"]:
            grid_cells.append(
                {
                    "cell_id": cell_id,
                    "center_lat": lat,
                    "center_lng": lng,
                    "lat_min": lat - lat_step / 2,
                    "lat_max": lat + lat_step / 2,
                    "lng_min": lng - lng_step / 2,
                    "lng_max": lng + lng_step / 2,
                }
            )
            cell_id += 1
            lng += lng_step
        lat += lat_step

    df = pd.DataFrame(grid_cells)
    print(f"✓ Created {len(df)} analysis grid cells")
    return df


def calculate_distance_matrix(grid_cells, places):
    """
    Calculate distance from each grid cell to each place.

    This is computationally the most expensive part but necessary
    for accurate accessibility analysis.

    Returns:
        DataFrame with cell_id, place_id, distance_km
    """
    print("\nCalculating distances (this may take a minute)...")

    distances = []

    for idx, cell in grid_cells.iterrows():
        cell_coords = (cell["center_lat"], cell["center_lng"])

        for _, place in places.iterrows():
            place_coords = (place["lat"], place["lng"])

            # Calculate geodesic distance (accounts for Earth's curvature)
            dist_km = geodesic(cell_coords, place_coords).kilometers

            distances.append(
                {
                    "cell_id": cell["cell_id"],
                    "place_id": place["place_id"],
                    "distance_km": dist_km,
                }
            )

        # Progress indicator
        if (idx + 1) % 20 == 0:
            print(f"  Processed {idx + 1}/{len(grid_cells)} cells...")

    df = pd.DataFrame(distances)
    print(f"✓ Calculated {len(df)} distance measurements")
    return df


def analyze_accessibility(grid_cells, places, distances, walking_distance_km=1.0):
    """
    Analyze service accessibility for each grid cell.

    Methodology based on 15-minute city framework (Moreno et al., 2021):
    - 15-minute walk ≈ 1.2km at average walking speed
    - We use 1.0km as conservative estimate

    Metrics calculated:
    1. Number of services within walking distance
    2. Distance to nearest service
    3. Average distance to 3 nearest services
    4. Service density (services per km²)

    Args:
        walking_distance_km: Maximum comfortable walking distance

    Returns:
        DataFrame with accessibility scores per grid cell
    """
    print(f"\nAnalyzing accessibility (walking distance: {walking_distance_km}km)...")

    results = []

    for cell_id in grid_cells["cell_id"]:
        # Get all distances for this cell
        cell_distances = distances[distances["cell_id"] == cell_id].copy()
        cell_distances = cell_distances.sort_values("distance_km")

        # Count services within walking distance
        within_walking = len(
            cell_distances[cell_distances["distance_km"] <= walking_distance_km]
        )

        # Distance to nearest
        nearest_distance = (
            cell_distances.iloc[0]["distance_km"] if len(cell_distances) > 0 else np.inf
        )

        # Average distance to 3 nearest (if available)
        top_3 = cell_distances.head(3)
        avg_distance_top3 = top_3["distance_km"].mean() if len(top_3) > 0 else np.inf

        # Service density calculation
        # Count services within 1km radius, calculate per km²
        services_1km = len(cell_distances[cell_distances["distance_km"] <= 1.0])
        density_per_km2 = services_1km / (np.pi * 1.0**2)  # Circle area with 1km radius

        results.append(
            {
                "cell_id": cell_id,
                "services_within_walking": within_walking,
                "nearest_distance_km": nearest_distance,
                "avg_distance_top3_km": avg_distance_top3,
                "density_per_km2": density_per_km2,
            }
        )

    df = pd.DataFrame(results)

    # Merge with grid cell coordinates
    df = df.merge(grid_cells[["cell_id", "center_lat", "center_lng"]], on="cell_id")

    print("✓ Accessibility analysis complete")
    return df


def identify_service_deserts(accessibility_df, threshold_distance_km=1.5):
    """
    Identify service deserts following USDA food desert methodology.

    A grid cell is considered a "service desert" if:
    1. Distance to nearest service > threshold (default 1.5km)
    2. Fewer than 2 services within walking distance (1km)

    This is conservative - assumes any underserved area is opportunity.
    Later we'll add population data to prioritize high-impact areas.

    References:
        USDA Economic Research Service - Food Access Research Atlas
        Cummins & Macintyre (2002) - Food desert methodology
    """
    deserts = accessibility_df[
        (accessibility_df["nearest_distance_km"] > threshold_distance_km)
        | (accessibility_df["services_within_walking"] < 2)
    ].copy()

    print(f"\n{'='*50}")
    print(f"SERVICE DESERT ANALYSIS")
    print(f"{'='*50}")
    print(f"Total grid cells analyzed: {len(accessibility_df)}")
    print(f"Service deserts identified: {len(deserts)}")
    print(f"Percentage underserved: {len(deserts)/len(accessibility_df)*100:.1f}%")
    print(f"{'='*50}\n")

    return deserts


def calculate_opportunity_scores(accessibility_df):
    """
    Calculate business opportunity scores for each grid cell.

    WITHOUT population data (we'll add this later), we score based on:
    1. Low competition (fewer nearby services = higher score)
    2. Not completely isolated (some foot traffic likely)
    3. Not oversaturated (too many services = lower score)

    Score components:
    - Competition gap: 40% (inverse of service density)
    - Accessibility gap: 40% (distance to nearest competitor)
    - Viability: 20% (not too isolated to be viable)

    Returns:
        DataFrame with opportunity_score column (0-10 scale)
    """
    df = accessibility_df.copy()

    # Normalize metrics to 0-1 scale

    # 1. Competition gap score (fewer services = higher score)
    # Inverse of density, normalized
    max_density = df["density_per_km2"].max()
    if max_density > 0:
        df["competition_gap"] = 1 - (df["density_per_km2"] / max_density)
    else:
        df["competition_gap"] = 1.0

    # 2. Accessibility gap score (farther from nearest = higher score)
    # But cap at reasonable distance (not TOO remote)
    df["accessibility_gap"] = df["nearest_distance_km"].clip(upper=3.0) / 3.0

    # 3. Viability score (sweet spot: some services nearby but not too many)
    # Areas with 1-3 services within 1km are "optimal" for new entry
    df["viability"] = df["services_within_walking"].apply(
        lambda x: 1.0 if 1 <= x <= 3 else 0.5 if x == 0 else max(0, 1 - (x - 3) / 10)
    )

    # Combined score (weighted)
    df["opportunity_score"] = (
        0.40 * df["competition_gap"]
        + 0.40 * df["accessibility_gap"]
        + 0.20 * df["viability"]
    ) * 10  # Scale to 0-10

    print("✓ Opportunity scores calculated")
    print(
        f"  Score range: {df['opportunity_score'].min():.2f} - {df['opportunity_score'].max():.2f}"
    )
    print(f"  Mean score: {df['opportunity_score'].mean():.2f}")

    return df


def save_analysis(df, city, business_type):
    """Save analysis results."""
    os.makedirs("data/processed", exist_ok=True)

    filename = f"data/processed/{city}_{business_type}_analysis_{datetime.now().strftime('%Y%m%d')}.csv"

    df.to_csv(filename, index=False)
    print(f"✓ Analysis saved: {filename}")
    return filename


# ============================================================================
# MAIN ANALYSIS WORKFLOW
# ============================================================================


def analyze_city(city="milan", business_type="pharmacy"):
    """
    Complete analysis workflow for a city and business type.

    This function orchestrates the entire analysis:
    1. Load collected place data
    2. Create analysis grid
    3. Calculate distances
    4. Analyze accessibility
    5. Identify service deserts
    6. Calculate opportunity scores
    7. Save results

    Example:
        results = analyze_city('milan', 'pharmacy')
    """
    print(f"\n{'='*60}")
    print(f"ANALYZING {city.upper()} - {business_type.upper()}")
    print(f"{'='*60}\n")

    # City boundaries (from collect_data.py)
    CITY_BOUNDS = {
        "milan": {"north": 45.535, "south": 45.395, "east": 9.280, "west": 9.065},
        "copenhagen": {
            "north": 55.727,
            "south": 55.615,
            "east": 12.650,
            "west": 12.453,
        },
        "bologna": {
            "north": 44.5450,
            "south": 44.4450,
            "east": 11.4000,
            "west": 11.2850,
        },
        "rome": {
            "north": 42.0500,
            "south": 41.7500,
            "east": 12.7000,
            "west": 12.3500,
        },
        "turin": {
            "north": 45.1300,
            "south": 45.0100,
            "east": 7.7500,
            "west": 7.6200,
        },
    }

    if city not in CITY_BOUNDS:
        raise ValueError(f"City {city} not configured. Available: {list(CITY_BOUNDS.keys())}")

    # 1. Load data
    places = load_data(city, business_type)

    # 2. Create analysis grid
    grid = create_analysis_grid(CITY_BOUNDS[city], grid_size_km=0.5)

    # 3. Calculate distances
    distances = calculate_distance_matrix(grid, places)

    # 4. Analyze accessibility
    accessibility = analyze_accessibility(grid, places, distances)

    # 5. Identify deserts
    deserts = identify_service_deserts(accessibility)

    # 6. Calculate opportunity scores
    results = calculate_opportunity_scores(accessibility)

    # 7. Save
    filename = save_analysis(results, city, business_type)

    print(f"\n{'='*60}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"\nTop 5 opportunity areas:")
    top5 = results.nlargest(5, "opportunity_score")[
        [
            "center_lat",
            "center_lng",
            "opportunity_score",
            "services_within_walking",
            "nearest_distance_km",
        ]
    ]
    print(top5.to_string())

    return results, deserts


def get_available_business_types(city):
    """Get list of business types that have been collected for a city."""
    data_dir = "data/raw"
    
    if not os.path.exists(data_dir):
        return []
    
    business_types = set()
    
    for file in os.listdir(data_dir):
        if file.startswith(f"{city}_") and file.endswith('.csv'):
            parts = file.replace('.csv', '').split('_')
            if len(parts) >= 3:
                business_type = parts[1]
                business_types.add(business_type)
    
    return sorted(list(business_types))


def analyze_all_business_types(city):
    """
    Analyze all available business types for a city.
    
    Args:
        city: City name (e.g., 'milan', 'copenhagen')
    
    Returns:
        Dictionary with results for each business type
    """
    business_types = get_available_business_types(city)
    
    if not business_types:
        print(f"❌ No data found for {city}")
        print("   Run data collection first: python src/collect_data.py")
        return {}
    
    print(f"\n{'='*70}")
    print(f"BATCH ANALYSIS - {city.upper()}")
    print(f"{'='*70}")
    print(f"Found {len(business_types)} business types to analyze:")
    print(f"  {', '.join(business_types)}")
    print(f"{'='*70}\n")
    
    results_summary = {}
    
    for idx, biz_type in enumerate(business_types, 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{len(business_types)}] Processing: {biz_type}")
        print(f"{'='*70}")
        
        try:
            results, deserts = analyze_city(city, biz_type)
            
            results_summary[biz_type] = {
                'status': 'success',
                'total_locations': len(load_data(city, biz_type)),
                'service_deserts': len(deserts),
                'avg_opportunity_score': results['opportunity_score'].mean(),
                'top_opportunity_score': results['opportunity_score'].max(),
            }
            
        except Exception as e:
            print(f"❌ Error analyzing {biz_type}: {e}")
            results_summary[biz_type] = {
                'status': 'error',
                'error': str(e)
            }
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"BATCH ANALYSIS COMPLETE - {city.upper()}")
    print(f"{'='*70}\n")
    
    print(f"{'Business Type':<20} {'Status':<10} {'Locations':>10} {'Deserts':>8} {'Avg Score':>10}")
    print(f"{'-'*70}")
    
    for biz_type, info in results_summary.items():
        if info['status'] == 'success':
            print(f"{biz_type:<20} {'✓':<10} {info['total_locations']:>10} "
                  f"{info['service_deserts']:>8} {info['avg_opportunity_score']:>10.2f}")
        else:
            print(f"{biz_type:<20} {'✗ ERROR':<10}")
    
    print(f"{'='*70}\n")
    
    return results_summary


if __name__ == "__main__":
    import sys
    
    print("Urban Opportunity Mapper - Analysis Module")
    print("="*70)
    
    # Check if arguments provided
    if len(sys.argv) > 1:
        city = sys.argv[1]
        
        if len(sys.argv) > 2:
            # Specific business type
            business_type = sys.argv[2]
            results, deserts = analyze_city(city, business_type)
        else:
            # All business types
            analyze_all_business_types(city)
    else:
        # Interactive mode
        print("\nWhat would you like to analyze?")
        print()
        print("1. Analyze ALL business types for Milan")
        print("2. Analyze specific business type for Milan")
        print("3. Analyze ALL business types for another city")
        print("4. Analyze specific business type for another city")
        print()
        
        choice = input("Enter choice (1-4): ").strip()
        
        if choice == '1':
            analyze_all_business_types('milan')
        
        elif choice == '2':
            available = get_available_business_types('milan')
            print(f"\nAvailable types: {', '.join(available)}")
            biz_type = input("Enter business type: ").strip()
            analyze_city('milan', biz_type)
        
        elif choice == '3':
            city = input("Enter city name: ").strip().lower()
            analyze_all_business_types(city)
        
        elif choice == '4':
            city = input("Enter city name: ").strip().lower()
            available = get_available_business_types(city)
            print(f"\nAvailable types: {', '.join(available)}")
            biz_type = input("Enter business type: ").strip()
            analyze_city(city, biz_type)
        
        else:
            print("Invalid choice")
    
    print("\n✓ Analysis complete!")
    print("Next: Run Streamlit dashboard to visualize")
    print("  streamlit run src/app_v1.py")