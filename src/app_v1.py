"""
Urban Opportunity Mapper - Interactive Dashboard
Streamlit application for exploring urban service distribution patterns
"""

import streamlit as st
import pandas as pd
import numpy as np
import folium
from folium.plugins import HeatMap, MarkerCluster
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
from glob import glob
import os
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Urban Opportunity Mapper",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #2c3e50;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #7f8c8d;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #3498db;
    }
    .insight-box {
        background-color: #e8f8f5;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #27ae60;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

@st.cache_data
def get_available_data():
    """Scan data directory and return available cities and business types."""
    raw_dir = 'data/raw'
    processed_dir = 'data/processed'
    
    available = {
        'cities': set(),
        'business_types': {}
    }
    
    # Check raw data
    if os.path.exists(raw_dir):
        for file in os.listdir(raw_dir):
            if file.endswith('.csv') and not file.endswith('summary.json'):
                parts = file.replace('.csv', '').split('_')
                if len(parts) >= 3:
                    city = parts[0]
                    biz_type = parts[1]
                    
                    available['cities'].add(city)
                    
                    if city not in available['business_types']:
                        available['business_types'][city] = []
                    
                    if biz_type not in available['business_types'][city]:
                        available['business_types'][city].append(biz_type)
    
    return available


@st.cache_data
def load_places_data(city, business_type):
    """Load raw places data for a city and business type."""
    pattern = f'data/raw/{city}_{business_type}_*.csv'
    files = glob(pattern)
    
    if not files:
        return None
    
    # Load most recent file
    latest_file = sorted(files)[-1]
    df = pd.read_csv(latest_file)
    
    return df


@st.cache_data
def load_analysis_data(city, business_type):
    """Load processed analysis data - prefer enriched > filtered > original."""
    
    # Priority 1: Enriched (with population)
    pattern = f'data/processed/{city}_{business_type}_analysis_filtered_*_enriched.csv'
    files = glob(pattern)
    
    # Priority 2: Just enriched (no filtered)
    if not files:
        pattern = f'data/processed/{city}_{business_type}_analysis_*_enriched.csv'
        files = glob(pattern)
    
    # Priority 3: Filtered (boundary corrected)
    if not files:
        pattern = f'data/processed/{city}_{business_type}_analysis_filtered_*.csv'
        files = glob(pattern)
    
    # Priority 4: Original
    if not files:
        pattern = f'data/processed/{city}_{business_type}_analysis_*.csv'
        files = glob(pattern)
    
    if not files:
        return None
    
    latest_file = sorted(files)[-1]
    df = pd.read_csv(latest_file)
    
    # Check if population data exists
    has_population = 'population_1km' in df.columns
    
    return df, has_population  # Always return tuple

# ============================================================================
# VISUALIZATION FUNCTIONS
# ============================================================================

def create_opportunity_map(places_df, analysis_df, business_type, show_layers):
    """Create interactive folium map - ALL locations, no lag."""
    
    center_lat = analysis_df['center_lat'].mean()
    center_lng = analysis_df['center_lng'].mean()
    
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=12,
        tiles='CartoDB positron',
        prefer_canvas=True
    )
    
    # Layer 1: ALL Service Locations - Using FastMarkerCluster
    if 'Service Locations' in show_layers:
        from folium.plugins import FastMarkerCluster
        
        # Prepare data in format FastMarkerCluster expects
        # This can handle 10,000+ markers efficiently
        locations_data = []
        
        for _, place in places_df.iterrows():
            rating = place.get('rating', 'N/A')
            rating_str = f"{rating:.1f}⭐" if pd.notna(rating) else "No rating"
            
            popup_html = f"""
            <div style="font-family: Arial; min-width: 150px;">
                <b>{place['name']}</b><br>
                {rating_str}<br>
                <small>{place.get('vicinity', '')}</small>
            </div>
            """
            
            locations_data.append([
                place['lat'],
                place['lng'],
                popup_html
            ])
        
        # Create fast marker cluster - handles ALL locations efficiently
        callback = ('function (row) {' 
                   'var marker = L.circleMarker(new L.LatLng(row[0], row[1]), '
                   '{color: "blue", radius: 4, fillOpacity: 0.6});'
                   'marker.bindPopup(row[2]);'
                   'return marker;};')
        
        FastMarkerCluster(
            locations_data,
            callback=callback,
            name='Service Locations (Click to Expand Clusters)'
        ).add_to(m)
        
        st.caption(f"ℹ️ Showing all {len(places_df)} locations (clustered for performance)")
    
    # Layer 2: Opportunity Heat Map
    if 'Opportunity Heat Map' in show_layers:
        heat_data = [
            [row['center_lat'], row['center_lng'], row['opportunity_score']] 
            for _, row in analysis_df.iterrows()
        ]
        
        HeatMap(
            heat_data,
            name='Opportunity Intensity',
            min_opacity=0.3,
            max_opacity=0.8,
            radius=25,
            blur=20,
            gradient={
                0.0: 'blue',
                0.3: 'lime', 
                0.5: 'yellow',
                0.7: 'orange',
                1.0: 'red'
            }
        ).add_to(m)
    
    # Layer 3: Clickable Grid Cells with Stats
    if 'Neighborhood Stats' in show_layers:
        grid_group = folium.FeatureGroup(name='Neighborhood Statistics (Click Any Area)', show=True)
        
        for _, cell in analysis_df.iterrows():
            # Color code by opportunity score
            score = cell['opportunity_score']
            if score >= 7.5:
                color = '#27ae60'  # High opportunity - green
                fill_color = '#27ae60'
            elif score >= 5.0:
                color = '#f39c12'  # Medium - orange
                fill_color = '#f39c12'
            elif score >= 2.5:
                color = '#3498db'  # Low - blue
                fill_color = '#3498db'
            else:
                color = '#95a5a6'  # Very low - gray
                fill_color = '#95a5a6'
            
            # Determine if it's a desert
            is_desert = (cell['nearest_distance_km'] > 1.5) or (cell['services_within_walking'] < 2)
            desert_marker = "⚠️ SERVICE DESERT" if is_desert else ""
            
            # Check if this analysis has population data
            has_population = 'population_1km' in cell and pd.notna(cell.get('population_1km'))
            
            if has_population:
                population_section = f"""
                    <tr style="background: #ecf0f1;">
                        <td colspan="2" style="padding-top: 8px;"><b>Demand Analysis</b></td>
                    </tr>
                    <tr>
                        <td><b>Population (1km):</b></td>
                        <td>{cell['population_1km']:,.0f}</td>
                    </tr>
                    <tr>
                        <td><b>Demand Score:</b></td>
                        <td>{cell.get('demand_score', 0)*10:.1f}/10</td>
                    </tr>
                """
            else:
                # No population data - show nothing or a placeholder
                population_section = ""
            
            # Build the complete popup HTML
            popup_html = f"""
            <div style="font-family: Arial; width: 280px; padding: 5px;">
                <h4 style="margin: 5px 0; color: #2c3e50;">
                    📍 Area Statistics {desert_marker}
                </h4>
                
                <table style="width: 100%; font-size: 12px; margin-top: 10px;">
                    <tr style="background: #ecf0f1;">
                        <td colspan="2"><b>Opportunity Analysis</b></td>
                    </tr>
                    <tr>
                        <td><b>Opportunity Score:</b></td>
                        <td>{cell['opportunity_score']:.1f}/10</td>
                    </tr>
                    <tr>
                        <td><b>Competition Gap:</b></td>
                        <td>{cell.get('competition_gap', 0)*10:.1f}/10</td>
                    </tr>
                    <tr>
                        <td><b>Accessibility Gap:</b></td>
                        <td>{cell.get('accessibility_gap', 0)*10:.1f}/10</td>
                    </tr>
                    
                    <tr style="background: #ecf0f1;">
                        <td colspan="2" style="padding-top: 8px;"><b>Service Accessibility</b></td>
                    </tr>
                    <tr>
                        <td><b>{business_type.title()}s in 1km:</b></td>
                        <td>{cell['services_within_walking']}</td>
                    </tr>
                    <tr>
                        <td><b>Nearest {business_type}:</b></td>
                        <td>{cell['nearest_distance_km']:.2f} km</td>
                    </tr>
                    <tr>
                        <td><b>Service Density:</b></td>
                        <td>{cell['density_per_km2']:.1f}/km²</td>
                    </tr>
                    <tr>
                        <td><b>Avg to 3 Nearest:</b></td>
                        <td>{cell.get('avg_distance_top3_km', 0):.2f} km</td>
                    </tr>
                    
                    {population_section}
                    
                    <tr style="background: #ecf0f1;">
                        <td colspan="2" style="padding-top: 8px;"><b>Location</b></td>
                    </tr>
                    <tr>
                        <td><b>Coordinates:</b></td>
                        <td>{cell['center_lat']:.4f}, {cell['center_lng']:.4f}</td>
                    </tr>
                </table>
                
                <p style="font-size: 11px; color: #7f8c8d; margin-top: 10px; padding-top: 8px; border-top: 1px solid #ddd;">
                    <b>Interpretation:</b><br>
                    {get_cell_interpretation(cell, is_desert, business_type)}
                </p>
            </div>
            """
            
            folium.Rectangle(
                bounds=[
                    [cell.get('lat_min', cell['center_lat'] - 0.0023), 
                     cell.get('lng_min', cell['center_lng'] - 0.0032)],
                    [cell.get('lat_max', cell['center_lat'] + 0.0023), 
                     cell.get('lng_max', cell['center_lng'] + 0.0032)]
                ],
                color=color,
                fill=True,
                fillColor=fill_color,
                fillOpacity=0.2,
                weight=1,
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(grid_group)
        
        grid_group.add_to(m)
    
    # Layer 4: Service Deserts
    if 'Service Deserts' in show_layers:
        deserts = analysis_df[
            (analysis_df['nearest_distance_km'] > 1.5) |
            (analysis_df['services_within_walking'] < 2)
        ]
        
        desert_group = folium.FeatureGroup(name='Service Deserts (Underserved)', show=False)
        
        for _, desert in deserts.iterrows():
            folium.Circle(
                location=[desert['center_lat'], desert['center_lng']],
                radius=250,
                color='#e74c3c',
                fill=True,
                fillColor='#e74c3c',
                fillOpacity=0.3,
                weight=2,
                popup=f"""<b>⚠️ Service Desert</b><br>
                Score: {desert['opportunity_score']:.1f}/10<br>
                Nearest: {desert['nearest_distance_km']:.2f}km"""
            ).add_to(desert_group)
        
        desert_group.add_to(m)
    
    # Layer 5: Top Opportunities
    if 'Top 10 Opportunities' in show_layers:
        top_opps = analysis_df.nlargest(10, 'opportunity_score')
        
        opp_group = folium.FeatureGroup(name='Top 10 Opportunities', show=True)
        
        for rank, (_, opp) in enumerate(top_opps.iterrows(), 1):
            folium.Marker(
                location=[opp['center_lat'], opp['center_lng']],
                popup=f"""
                <b>🌟 Opportunity #{rank}</b><br>
                Score: {opp['opportunity_score']:.1f}/10<br>
                Nearest: {opp['nearest_distance_km']:.2f}km<br>
                In 1km: {opp['services_within_walking']}
                """,
                tooltip=f"Opportunity #{rank}",
                icon=folium.Icon(color='green', icon='star', prefix='fa')
            ).add_to(opp_group)
        
        opp_group.add_to(m)
    
    folium.LayerControl(collapsed=False).add_to(m)
    
    return m


def get_cell_interpretation(cell, is_desert, business_type):
    """Generate human-readable interpretation of cell stats."""
    score = cell['opportunity_score']
    services = cell['services_within_walking']
    has_population = 'population_1km' in cell and pd.notna(cell.get('population_1km'))
    
    if is_desert:
        if has_population and cell.get('population_1km', 0) > 1000:
            return f"This area lacks adequate {business_type} access despite having {cell['population_1km']:,.0f} residents. High opportunity for new entry with significant social impact."
        else:
            return f"This area lacks adequate {business_type} access. Potential opportunity if population develops."
    
    elif score >= 7.5:
        if has_population:
            return f"Excellent opportunity: low competition, accessibility gap, and {cell['population_1km']:,.0f} potential customers."
        else:
            return f"Excellent opportunity: low competition, accessibility gap, viable location."
    
    elif score >= 5.0:
        return f"Moderate opportunity: some existing services but room for growth."
    
    elif services > 10:
        return f"Market saturation: {services} existing services indicate high competition."
    
    else:
        if has_population and cell.get('population_1km', 0) == 0:
            return f"Low opportunity: unpopulated area (likely industrial, parkland, or infrastructure)."
        else:
            return f"Competitive area with adequate service coverage."


def create_distribution_chart(analysis_df):
    """Create histogram of opportunity scores."""
    fig = px.histogram(
        analysis_df,
        x='opportunity_score',
        nbins=20,
        title='Distribution of Opportunity Scores',
        labels={'opportunity_score': 'Opportunity Score (0-10)', 'count': 'Number of Areas'},
        color_discrete_sequence=['#3498db']
    )
    
    fig.update_layout(
        showlegend=False,
        height=300
    )
    
    return fig


def create_accessibility_chart(analysis_df):
    """Create chart showing service accessibility."""
    fig = px.scatter(
        analysis_df,
        x='nearest_distance_km',
        y='services_within_walking',
        color='opportunity_score',
        title='Service Accessibility vs Opportunity',
        labels={
            'nearest_distance_km': 'Distance to Nearest Service (km)',
            'services_within_walking': 'Services Within 1km',
            'opportunity_score': 'Opportunity Score'
        },
        color_continuous_scale='RdYlGn',
        height=400
    )
    
    return fig


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Header
    st.markdown('<p class="main-header">🌍 Urban Opportunity Mapper</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">Analyzing urban service distribution for business opportunities and livability</p>',
        unsafe_allow_html=True
    )
    
    # Load available data
    available = get_available_data()
    
    if not available['cities']:
        st.error("No data found! Please run data collection first.")
        st.code("python src/collect_data.py")
        return
    
    # Sidebar controls
    st.sidebar.header("🎛️ Controls")
    
    # City selector
    city = st.sidebar.selectbox(
        "Select City",
        sorted(list(available['cities'])),
        format_func=lambda x: x.title()
    )
    
    # Business type selector
    if city in available['business_types']:
        business_types = sorted(available['business_types'][city])
        
        business_type = st.sidebar.selectbox(
            "Business Type",
            business_types,
            format_func=lambda x: x.replace('_', ' ').title()
        )
    else:
        st.error(f"No data found for {city}")
        return
    
    # View mode
    view_mode = st.sidebar.radio(
        "View Mode",
        ["Business Opportunity Analysis", "Service Distribution Overview"]
    )
    
    # Map layers
    st.sidebar.markdown("---")
    st.sidebar.subheader("Map Layers")
    
    layer_options = [
        'Service Locations',
        'Opportunity Heat Map',
        'Neighborhood Stats',  # NEW - clickable grid
        'Service Deserts',
        'Top 10 Opportunities'
    ]

    show_layers = []
    for layer in layer_options:
        # Default: show Neighborhood Stats and Top Opportunities
        default_on = layer in ['Neighborhood Stats', 'Top 10 Opportunities']
        if st.sidebar.checkbox(layer, value=default_on):
            show_layers.append(layer)
    
    # Load data
    places_df = load_places_data(city, business_type)
    analysis_result = load_analysis_data(city, business_type)

    if places_df is None:
        st.error(f"No raw data found for {city} - {business_type}")
        return

    # Unpack the tuple properly
    if analysis_result is None:
        st.warning(f"⚠️ Analysis not yet run for {business_type} in {city}")
        return

    # Unpack the tuple - THIS IS THE KEY FIX
    if isinstance(analysis_result, tuple):
        analysis_df, has_population = analysis_result
    else:
        # Fallback for old data format
        analysis_df = analysis_result
        has_population = 'population_1km' in analysis_df.columns if analysis_df is not None else False

    # Now analysis_df is the actual DataFrame, not a tuple

    if analysis_df is None:
        st.warning(f"⚠️ Analysis not yet run for {business_type} in {city}")
        
        st.info(f"""
        **To generate analysis, run:**
    ```bash
        python src/analyze.py {city} {business_type}
    ```
        
        Or analyze all business types at once:
    ```bash
        python src/analyze.py {city}
    ```
        """)
        
        return

    # ========================================================================
    # METRICS ROW
    # ========================================================================

    st.markdown("### 📊 Key Metrics")

    # Show population status
    if has_population:
        st.success("✅ Analysis includes population demand data")
    else:
        st.warning("⚠️ Population data not yet integrated. Run: `python src/population_data.py milan`")

    # Create metrics - adjust number of columns based on whether we have population
    if has_population:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
    else:
        col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "Total Services",
            f"{len(places_df):,}",
            help=f"Number of {business_type}s found in {city}"
        )

    with col2:
        deserts = len(analysis_df[
            (analysis_df['nearest_distance_km'] > 1.5) |
            (analysis_df['services_within_walking'] < 2)
        ])
        desert_pct = (deserts / len(analysis_df)) * 100
        st.metric(
            "Service Deserts",
            deserts,
            f"{desert_pct:.1f}% of areas",
            delta_color="inverse"
        )

    with col3:
        avg_score = analysis_df['opportunity_score'].mean()
        st.metric(
            "Avg Opportunity",
            f"{avg_score:.1f}/10",
            help="Average opportunity score across all areas"
        )

    with col4:
        if places_df['rating'].notna().sum() > 0:
            avg_rating = places_df['rating'].mean()
            st.metric(
                "Avg Service Rating",
                f"{avg_rating:.1f}⭐",
                help="Average rating from Google reviews"
            )
        else:
            st.metric("Avg Service Rating", "N/A")

    with col5:
        avg_density = analysis_df['density_per_km2'].mean()
        st.metric(
            "Avg Density",
            f"{avg_density:.1f}/km²",
            help="Average number of services per square kilometer"
        )

    # Only show population metric if we have the data
    if has_population:
        with col6:
            total_pop = analysis_df['population_1km'].sum()
            st.metric(
                "Total Population",
                f"{total_pop:,.0f}",
                help="Total population in analyzed area"
            )
        
    # ========================================================================
    # MAIN CONTENT
    # ========================================================================
    
    if view_mode == "Business Opportunity Analysis":
        
        # Map
        st.markdown("### 🗺️ Opportunity Map")
        
        st.info(f"""
        **How to read this map:**
        - 🔴 **Red/Hot areas** = High opportunity (low competition, accessibility gap)
        - 🟢 **Green stars** = Top 10 best opportunities
        - ⭕ **Red circles** = Service deserts (underserved areas)
        - 🔵 **Blue dots** = Existing {business_type}s
        """)
        
        m = create_opportunity_map(places_df, analysis_df, business_type, show_layers)
        st_folium(m, width=1400, height=600)
        
        # Top opportunities table
        st.markdown("### ⭐ Top 10 Opportunities")
        
        top_opps = analysis_df.nlargest(10, 'opportunity_score')[[
            'center_lat', 'center_lng', 'opportunity_score',
            'services_within_walking', 'nearest_distance_km', 'density_per_km2'
        ]].copy()
        
        top_opps.columns = [
            'Latitude', 'Longitude', 'Score (0-10)',
            'Services in 1km', 'Nearest Competitor (km)', 'Density (/km²)'
        ]
        
        top_opps['Score (0-10)'] = top_opps['Score (0-10)'].round(2)
        top_opps['Nearest Competitor (km)'] = top_opps['Nearest Competitor (km)'].round(2)
        top_opps['Density (/km²)'] = top_opps['Density (/km²)'].round(1)
        
        st.dataframe(
            top_opps.reset_index(drop=True),
            width='stretch',
            height=400
        )
        
        # Insights
        st.markdown("### 💡 Key Insights")
        
        col1, col2 = st.columns(2)
        
        with col1:
            high_opp = len(analysis_df[analysis_df['opportunity_score'] > 7])
            st.markdown(f"""
            <div class="insight-box">
                <b>🎯 High Opportunity Areas</b><br>
                Found <b>{high_opp}</b> areas with opportunity score > 7.0<br>
                These represent <b>{(high_opp/len(analysis_df)*100):.1f}%</b> of the city
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            underserved = len(analysis_df[analysis_df['services_within_walking'] == 0])
            st.markdown(f"""
            <div class="insight-box">
                <b>⚠️ Zero Coverage Areas</b><br>
                <b>{underserved}</b> areas have NO {business_type}s within 1km<br>
                Representing potential social equity gaps
            </div>
            """, unsafe_allow_html=True)
        
        # Charts
        st.markdown("### 📈 Statistical Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            fig1 = create_distribution_chart(analysis_df)
            st.plotly_chart(fig1, width='stretch')
        
        with col2:
            fig2 = create_accessibility_chart(analysis_df)
            st.plotly_chart(fig2, width='stretch')
    
    else:  # Service Distribution Overview
        
        st.markdown("### 🗺️ Service Distribution Map")
        
        m = create_opportunity_map(places_df, analysis_df, business_type, show_layers)
        st_folium(m, width=1400, height=600)
        
        # Service quality analysis
        if places_df['rating'].notna().sum() > 0:
            st.markdown("### ⭐ Service Quality Distribution")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                excellent = len(places_df[places_df['rating'] >= 4.5])
                st.metric("Excellent (≥4.5⭐)", excellent, f"{excellent/len(places_df)*100:.1f}%")
            
            with col2:
                good = len(places_df[(places_df['rating'] >= 4.0) & (places_df['rating'] < 4.5)])
                st.metric("Good (4.0-4.5⭐)", good, f"{good/len(places_df)*100:.1f}%")
            
            with col3:
                below = len(places_df[places_df['rating'] < 4.0])
                st.metric("Below Average (<4.0⭐)", below, f"{below/len(places_df)*100:.1f}%")
            
            # Rating distribution chart
            fig = px.histogram(
                places_df[places_df['rating'].notna()],
                x='rating',
                nbins=20,
                title=f'Rating Distribution for {business_type.title()}s in {city.title()}',
                labels={'rating': 'Rating (⭐)', 'count': 'Number of Services'}
            )
            st.plotly_chart(fig, width='stretch')
    
    # ========================================================================
    # FOOTER
    # ========================================================================
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        **Data Collection**  
        Date: {datetime.now().strftime('%Y-%m-%d')}  
        Grid Size: 500m × 500m  
        Analysis Cells: {len(analysis_df)}
        """)
    
    with col2:
        st.markdown("""
        **Methodology**  
        - 15-minute city framework (Moreno et al.)
        - 2SFCA spatial accessibility (Langford & Higgs)
        - Grid-based sampling (Stopher & Stanley)
        """)
    
    with col3:
        st.markdown("""
        **Technology Stack**  
        - Google Maps Places API
        - Folium mapping
        - Streamlit dashboard
        """)


if __name__ == "__main__":
    main()