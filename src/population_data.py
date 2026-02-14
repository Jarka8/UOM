"""
Add population density data to analysis using WorldPop dataset.
This filters out empty areas and weights opportunities by demand.
"""

import pandas as pd
import numpy as np
import os
from glob import glob


def download_worldpop_data_manual_instructions(country='ITA', year=2020):
    """
    Provide instructions for manual download since automated download URLs change.
    """
    print(f"\n{'='*70}")
    print("WORLDPOP DATA DOWNLOAD REQUIRED")
    print(f"{'='*70}\n")
    
    print("The automated download isn't working. Please download manually:")
    print()
    print("1. Go to: https://hub.worldpop.org/geodata/listing?id=76")
    print()
    print("2. Search for 'Italy' or scroll to find Italy")
    print()
    print("3. Download the file:")
    print("   - 'Italy 2020 Constrained individual countries 2000-2020 (1km resolution)'")
    print("   - OR 'ita_ppp_2020_1km_Aggregated.tif'")
    print()
    print("4. Save it to:")
    output_dir = 'data/population'
    os.makedirs(output_dir, exist_ok=True)
    output_file = f'{output_dir}/worldpop_ITA_2020.tif'
    print(f"   {os.path.abspath(output_file)}")
    print()
    print("5. Then re-run this script")
    print()
    print(f"{'='*70}\n")
    
    return output_file


def check_for_existing_population_data():
    """Check if population data already exists."""
    possible_files = [
        'data/population/worldpop_ITA_2020.tif',
        'data/population/ita_ppp_2020_1km_Aggregated.tif',
        'data/population/ita_ppp_2020.tif',
    ]
    
    for filepath in possible_files:
        if os.path.exists(filepath):
            print(f"✓ Found existing population data: {filepath}")
            return filepath
    
    return None


def get_population_for_point(lat, lng, raster_path):
    """
    Get population density at a specific lat/lng from raster.
    
    Returns:
        Population count (people per pixel)
    """
    try:
        import rasterio
        from rasterio.transform import rowcol
    except ImportError:
        print("ERROR: rasterio not installed")
        print("Run: pip install rasterio")
        return 0
    
    try:
        with rasterio.open(raster_path) as src:
            # Convert lat/lng to raster row/col
            row, col = rowcol(src.transform, lng, lat)
            
            # Read the value at that pixel
            if row < 0 or col < 0 or row >= src.height or col >= src.width:
                return 0
            
            value = src.read(1)[row, col]
            
            # WorldPop uses -99999 or very negative numbers for NoData
            if value < 0:
                return 0
            
            return float(value)
    except Exception as e:
        print(f"Warning: Could not read population at ({lat}, {lng}): {e}")
        return 0


def add_population_to_analysis(city='milan', country='ITA'):
    """
    Add population data to all existing analysis files.
    
    This enriches your opportunity scoring with demand data!
    """
    print(f"\n{'='*70}")
    print(f"ADDING POPULATION DATA TO {city.upper()} ANALYSES")
    print(f"{'='*70}\n")
    
    # Check for existing population data
    pop_raster = check_for_existing_population_data()
    
    if not pop_raster:
        # Provide manual download instructions
        expected_path = download_worldpop_data_manual_instructions(country)
        
        print("⏸️  Script paused. Please download the file and re-run.")
        return
    
    # Find all analysis files for this city
    pattern = f'data/processed/{city}_*_analysis_filtered_*.csv'
    files = glob(pattern)
    
    if not files:
        # Try non-filtered versions
        pattern = f'data/processed/{city}_*_analysis_*.csv'
        files = glob(pattern)
        files = [f for f in files if '_enriched' not in f]  # Skip already enriched
    
    if not files:
        print(f"❌ No analysis files found for {city}")
        print(f"   Run analysis first: python src/analyze.py {city}")
        return
    
    print(f"Found {len(files)} analysis files to enrich\n")
    
    for filepath in files:
        # Skip if already enriched
        if '_enriched' in filepath:
            print(f"⏭️  Skipping (already enriched): {filepath}")
            continue
        
        print(f"Processing: {os.path.basename(filepath)}")
        
        # Load analysis
        df = pd.read_csv(filepath)
        
        # Add population column
        print("  📊 Extracting population data...")
        populations = []
        
        for idx, row in df.iterrows():
            pop = get_population_for_point(
                row['center_lat'],
                row['center_lng'],
                pop_raster
            )
            populations.append(pop)
            
            if (idx + 1) % 20 == 0:
                print(f"     Processed {idx + 1}/{len(df)} cells...")
        
        df['population'] = populations
        
        # Calculate population within 1km radius
        print("  🔍 Calculating 1km radius population...")
        
        from geopy.distance import geodesic
        
        pop_1km = []
        for idx, cell in df.iterrows():
            cell_coords = (cell['center_lat'], cell['center_lng'])
            
            # Find all cells within ~1km
            nearby_pop = 0
            for _, other_cell in df.iterrows():
                other_coords = (other_cell['center_lat'], other_cell['center_lng'])
                dist = geodesic(cell_coords, other_coords).kilometers
                
                if dist <= 1.0:
                    nearby_pop += other_cell['population']
            
            pop_1km.append(nearby_pop)
            
            if (idx + 1) % 20 == 0:
                print(f"     Processed {idx + 1}/{len(df)} cells...")
        
        df['population_1km'] = pop_1km
        
        # Recalculate opportunity scores with population weighting
        print("  🎯 Recalculating opportunity scores with demand data...")
        
        df = recalculate_opportunity_with_population(df)
        
        # Save enriched version
        new_filepath = filepath.replace('.csv', '_enriched.csv')
        df.to_csv(new_filepath, index=False)
        
        # Stats
        total_pop = df['population_1km'].sum()
        avg_pop = df['population_1km'].mean()
        cells_with_pop = len(df[df['population_1km'] > 0])
        
        print(f"  ✅ Saved: {os.path.basename(new_filepath)}")
        print(f"     Total population: {total_pop:,.0f}")
        print(f"     Avg per cell (1km): {avg_pop:,.0f}")
        print(f"     Populated cells: {cells_with_pop}/{len(df)}")
        print(f"     Empty cells: {len(df[df['population_1km'] == 0])}")
        print()
    
    print(f"{'='*70}")
    print("✅ COMPLETE!")
    print(f"{'='*70}\n")
    print("Your opportunity scores now account for population demand!")
    print("Areas with zero population are automatically deprioritized.")
    print()
    print("Next step: Refresh your Streamlit app to see updated scores!")


def recalculate_opportunity_with_population(df):
    """
    Recalculate opportunity scores incorporating population demand.
    
    New formula:
    - Competition gap: 30% (supply side)
    - Accessibility gap: 30% (supply side)
    - Demand: 30% (NEW - population in area)
    - Viability: 10% (minimum threshold)
    """
    # Normalize population to 0-1 scale
    max_pop = df['population_1km'].max()
    if max_pop > 0:
        df['demand_score'] = df['population_1km'] / max_pop
    else:
        df['demand_score'] = 0
    
    # Filter out very low-population areas
    # These shouldn't be opportunities regardless of supply metrics
    df.loc[df['population_1km'] < 100, 'demand_score'] = 0
    
    # Keep original score for comparison
    df['opportunity_score_original'] = df['opportunity_score']
    
    # Recalculate opportunity score with demand component
    df['opportunity_score'] = (
        0.30 * df.get('competition_gap', 0) +
        0.30 * df.get('accessibility_gap', 0) +
        0.30 * df['demand_score'] +
        0.10 * df.get('viability', 0.5)
    ) * 10  # Scale to 0-10
    
    # Zero out scores for areas with minimal population
    df.loc[df['population_1km'] < 100, 'opportunity_score'] = 0
    
    # Print comparison
    orig_avg = df['opportunity_score_original'].mean()
    new_avg = df['opportunity_score'].mean()
    zeroed = len(df[df['opportunity_score'] == 0])
    
    print(f"     Opportunity scores updated:")
    print(f"     - Original average: {orig_avg:.2f}/10")
    print(f"     - New average: {new_avg:.2f}/10")
    print(f"     - Cells zeroed (low population): {zeroed}")
    
    return df


if __name__ == "__main__":
    import sys
    
    # Check for rasterio
    try:
        import rasterio
    except ImportError:
        print("❌ Missing required library: rasterio")
        print()
        print("Install it with:")
        print("  pip install rasterio")
        print()
        sys.exit(1)
    
    city = sys.argv[1] if len(sys.argv) > 1 else 'milan'
    country = 'ITA' if city in ['milan', 'rome', 'bologna', 'turin'] else 'DNK'
    
    add_population_to_analysis(city, country)
