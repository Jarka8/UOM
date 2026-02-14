"""
Visualization module - Creates interactive maps.

Generates HTML maps showing:
- Service locations
- Service deserts (underserved areas)
- Opportunity heat map
- Comparative city views
"""

import pandas as pd
import folium
from folium.plugins import HeatMap
import os


def create_opportunity_map(analysis_df, places_df, city_name, business_type):
    """
    Create interactive map with opportunity zones and service deserts.
    
    Map layers:
    1. Base: Service locations (blue markers)
    2. Heat map: Opportunity scores (red = high opportunity)
    3. Markers: Service desert areas (red circles)
    4. Info: Click cells for detailed scores
    """
    # Center map on city
    center_lat = analysis_df['center_lat'].mean()
    center_lng = analysis_df['center_lng'].mean()
    
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=12,
        tiles='OpenStreetMap'
    )
    
    # Layer 1: Existing service locations (small blue markers)
    service_group = folium.FeatureGroup(name=f'Existing {business_type}s')
    
    for _, place in places_df.iterrows():
        folium.CircleMarker(
            location=[place['lat'], place['lng']],
            radius=3,
            color='blue',
            fill=True,
            fillColor='blue',
            fillOpacity=0.6,
            popup=f"{place['name']}<br>Rating: {place.get('rating', 'N/A')}★"
        ).add_to(service_group)
    
    service_group.add_to(m)
    
    # Layer 2: Opportunity heat map
    # Higher scores = redder/hotter
    heat_data = [
        [row['center_lat'], row['center_lng'], row['opportunity_score']]
        for _, row in analysis_df.iterrows()
    ]
    
    HeatMap(
        heat_data,
        name='Opportunity Heat Map',
        min_opacity=0.3,
        max_opacity=0.8,
        radius=25,
        blur=20,
        gradient={
            0.0: 'green',   # Low opportunity
            0.5: 'yellow',  # Medium
            0.7: 'orange',
            1.0: 'red'      # High opportunity
        }
    ).add_to(m)
    
    # Layer 3: Service deserts (areas needing services)
    desert_group = folium.FeatureGroup(name='Service Deserts')
    
    deserts = analysis_df[
        (analysis_df['nearest_distance_km'] > 1.5) |
        (analysis_df['services_within_walking'] < 2)
    ]
    
    for _, desert in deserts.iterrows():
        folium.Circle(
            location=[desert['center_lat'], desert['center_lng']],
            radius=250,  # 250m radius circle
            color='red',
            fill=True,
            fillColor='red',
            fillOpacity=0.3,
            popup=f"""
                <b>Service Desert</b><br>
                Opportunity Score: {desert['opportunity_score']:.1f}/10<br>
                Nearest {business_type}: {desert['nearest_distance_km']:.2f}km<br>
                Services within 1km: {desert['services_within_walking']}<br>
                Density: {desert['density_per_km2']:.1f}/km²
            """
        ).add_to(desert_group)
    
    desert_group.add_to(m)
    
    # Layer 4: Top opportunities (markers for best locations)
    top_opportunities = analysis_df.nlargest(10, 'opportunity_score')
    
    opportunity_group = folium.FeatureGroup(name='Top 10 Opportunities')
    
    for idx, opp in top_opportunities.iterrows():
        folium.Marker(
            location=[opp['center_lat'], opp['center_lng']],
            popup=f"""
                <b>Opportunity #{idx + 1}</b><br>
                Score: {opp['opportunity_score']:.1f}/10<br>
                <br>
                <b>Competition Analysis:</b><br>
                Services within 1km: {opp['services_within_walking']}<br>
                Nearest competitor: {opp['nearest_distance_km']:.2f}km<br>
                Density: {opp['density_per_km2']:.1f}/km²<br>
                <br>
                <b>Why this is an opportunity:</b><br>
                {'Low competition area' if opp['services_within_walking'] < 3 else 'Underserved despite demand'}
            """,
            icon=folium.Icon(color='green', icon='star', prefix='fa')
        ).add_to(opportunity_group)
    
    opportunity_group.add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    # Add title
    title_html = f'''
    <div style="position: fixed; 
                top: 10px; left: 50px; width: 400px; height: 90px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <h4>{city_name.title()} - {business_type.title()} Opportunity Map</h4>
    <p style="font-size:12px; margin:5px 0;">
    🔵 Blue dots = Existing services<br>
    🔴 Red areas = Service deserts<br>
    ⭐ Green stars = Top opportunities
    </p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Save map
    os.makedirs('./outputs', exist_ok=True)
    filename = f"./outputs/{city_name}_{business_type}_opportunity_map.html"
    m.save(filename)
    
    print(f"\n✓ Map created: {filename}")
    print(f"  Open in browser to view interactive map!")
    
    return filename


def create_comparison_map(milan_df, copenhagen_df, business_type):
    """
    Create side-by-side comparison (for later when you have both cities).
    """
    # TODO: Implement this in Week 3
    pass


if __name__ == "__main__":
    # Load latest analysis
    analysis_file = max([
        f for f in os.listdir('src/data/processed') 
        if f.startswith('milan_pharmacy_analysis')
    ])
    
    analysis_df = pd.read_csv(f'src/data/processed/{analysis_file}')
    
    # Load original places data
    places_file = max([
        f for f in os.listdir('src/data/raw')
        if f.startswith('milan_pharmacy')
    ])
    
    places_df = pd.read_csv(f'src/data/raw/{places_file}')
    
    # Create map
    create_opportunity_map(analysis_df, places_df, 'milan', 'pharmacy')