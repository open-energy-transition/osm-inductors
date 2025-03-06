import pandas as pd
import re
import json
import requests
from geopy.distance import geodesic
from fuzzywuzzy import process
from scipy.spatial import KDTree
import numpy as np


# ---------------------- CONFIGURATION ---------------------- #
# Specify the country you want to analyze. Adjust the 'COUNTRY_NAME' and 'country_code' accordingly.
COUNTRY_NAME = "India"  # Example: "Germany", "Brazil", "France"
country_code = "Q668"   # Country code according to Wikidata
max_distance_km = 0.7  #max_distance_km (float): The maximum distance to consider a match (in kilometers).    
mismatch_threshold_km = 0.5 #mismatch_threshold_km (float): The threshold distance beyond which the coordinates are considered mismatched.

# ---------------------- Wikidata Query Function ---------------------- #

def fetch_wikidata_power_plants(country):
    """
    Fetches power plants from Wikidata using the SPARQL API.

    Args:
        country (str): The name of the country to fetch power plant data for.

    Returns:
        pd.DataFrame: A DataFrame containing information about power plants from Wikidata.
    """
    url = "https://query.wikidata.org/sparql"
    
    query = f"""
    SELECT ?plant ?plantLabel ?location ?coordinates WHERE {{
        ?plant wdt:P31/wdt:P279* wd:Q159719.  # Instance of (or subclass of) power plant
        ?plant wdt:P17 wd:{country_code}.               # Country = India (Q668)
        OPTIONAL {{ ?plant wdt:P625 ?coordinates. }}  # Coordinates if available
        OPTIONAL {{ ?plant wdt:P276 ?location. }}  # Location if available
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
    }}"""
    
    headers = {"Accept": "application/json"}
    response = requests.get(url, params={"query": query, "format": "json"}, headers=headers)

    # If the request is successful, process the returned data
    if response.status_code == 200:
        data = response.json()["results"]["bindings"]
        plants = []
        
        # Process each item in the response data
        for item in data:
            wikidata_id = item['plant']['value']
            name = item["plantLabel"]["value"]
            location = item.get("location", {}).get("value", "Unknown")
            coords = item.get("coordinates", {}).get("value", None)
            latitude, longitude = extract_coordinates(coords) if coords else (None, None)
            plants.append({
                "wikidata_id": wikidata_id,
                "plantLabel": name,
                "latitude": latitude,
                "longitude": longitude,
                "location": location
            })
        
        # Return as DataFrame
        df_wiki = pd.DataFrame(plants)
        df_wiki.to_csv('wikidataset.csv')
        return df_wiki
    else:
        print(f"❌ Error fetching Wikidata data: {response.status_code}")
        return pd.DataFrame()


# ---------------------- Overpass API Query Function ---------------------- #

def fetch_osm_power_plants(country):
    """
    Fetches power plants from OpenStreetMap using Overpass API and returns all available information.

    Args:
        country (str): The name of the country to fetch power plant data for.

    Returns:
        pd.DataFrame: A DataFrame containing information about power plants from OSM.
    """
    url = "http://overpass-api.de/api/interpreter"
    
    query = f"""
    [out:json][timeout:1800][maxsize:107374182];
    area[name="{country}"]->.searchArea;
    (
      node["power"="plant"](area.searchArea);
      way["power"="plant"](area.searchArea);
      relation["power"="plant"](area.searchArea);
    );
    out body tags center;
    """
    
    response = requests.get(url, params={"data": query})
    
    # If the request is successful, process the returned data
    if response.status_code == 200:
        data = response.json()["elements"]
        plants = []
        
        # Process each item in the response data
        for item in data:
            tags = item.get("tags", {})
            plant_info = {
                "id": str(item.get("id")),  # Ensure ID is a string to prevent KeyError
                "name": tags.get("name", f"Unnamed-{item.get('id')}"),  # Extract name if available
                "type": item.get("type"),
                "latitude": item.get("lat") or item.get("center", {}).get("lat"),
                "longitude": item.get("lon") or item.get("center", {}).get("lon"),
                "tags": tags  # Store all tags as a dictionary
            }
            plants.append(plant_info)

        # Return as DataFrame
        df_osm = pd.DataFrame(plants)
        df_osm.to_csv('osm_api_dataset.csv')
        print(f"✅ Power plants found in OSM database: {len(df_osm)}")
        return df_osm
    else:
        print(f"❌ Error fetching OSM data: {response.status_code}")
        return pd.DataFrame()


# ---------------------- Data Processing Functions ---------------------- #

def extract_coordinates(coord_string):
    """
    Extracts (latitude, longitude) from Wikidata's 'Point(Longitude Latitude)' format.

    Args:
        coord_string (str): The coordinate string in the format 'Point(Longitude Latitude)'.

    Returns:
       latitude and longitude as floats.
    """
    match = re.search(r"Point\(([-\d.]+) ([-\d.]+)\)", str(coord_string))
    return (float(match.group(2)), float(match.group(1))) if match else (None, None)


def normalize_name(name):
    """
    Normalize power plant names by converting to lowercase and removing extra spaces.

    Args:
        name (str): The name of the power plant.

    Returns:
        str: The normalized name.
    """
    if isinstance(name, str):
        return " ".join(name.lower().split())
    return name


def compare_osm_to_wikidata(osm_df, wikidata_df, max_distance_km=0.01, mismatch_threshold_km=0.005):
    """
    Compares OSM power plants to Wikidata power plants.
    Identifies:
    - Missing power plants in Wikidata (to be used for QuickStatements)
    - Coordinate mismatches
    - Wikidata entries missing coordinates

    Args:
        osm_df (pd.DataFrame): The DataFrame of power plants from OpenStreetMap.
        wikidata_df (pd.DataFrame): The DataFrame of power plants from Wikidata.
        max_distance_km (float): The maximum distance to consider a match (in kilometers).
        mismatch_threshold_km (float): The threshold distance beyond which the coordinates are considered mismatched.

    Returns:
        three dataframes:
            - Missing power plants in Wikidata
            - Coordinate mismatches
            - Wikidata entries missing coordinates
    """
    missing_in_wikidata, different_coordinates, wikidata_missing_coordinates = [], [], []

    # Normalize names in both datasets
    osm_df["normalized_name"] = osm_df["name"].apply(normalize_name)
    wikidata_df["normalized_name"] = wikidata_df["plantLabel"].apply(normalize_name)

    # Step 1: Exclude OSM power plants that already have a Wikidata reference (direct or indirect)
    def extract_wikidata_tags(tags):
        if not isinstance(tags, dict):
            return None
        for key, value in tags.items():
            if "wikidata" in key and isinstance(value, str) and value.startswith("Q"):
                return value  # Extract any Wikidata QID reference
        return None

    osm_df["wikidata_id"] = osm_df["tags"].apply(extract_wikidata_tags)
    osm_filtered = osm_df[osm_df["wikidata_id"].isna()].copy()

    # Identify power plants that are missing from Wikidata by normalized name
    osm_filtered = osm_filtered[~osm_filtered["normalized_name"].isin(wikidata_df["normalized_name"])]

    # Separate remaining entries with and without coordinates
    osm_with_coords = osm_filtered.dropna(subset=["latitude", "longitude"]).copy()
    wikidata_with_coords = wikidata_df.dropna(subset=["latitude", "longitude"]).copy()
    wikidata_missing_coords = wikidata_df[wikidata_df[["latitude", "longitude"]].isna().any(axis=1)].copy()

    # Check which power plants in osm_with_coords are not present in wikidata_df
    if not osm_with_coords.empty and not wikidata_with_coords.empty:
        osm_tree = KDTree(wikidata_with_coords[["latitude", "longitude"]].to_numpy())
        distances, indices = osm_tree.query(osm_with_coords[["latitude", "longitude"]].to_numpy())

        for i, (dist, index) in enumerate(zip(distances, indices)):
            osm_row = osm_with_coords.iloc[i]
            wikidata_row = wikidata_with_coords.iloc[index]
            
            if dist >= max_distance_km:  # If no close match in Wikidata, add to missing
                missing_in_wikidata.append({
                    "name": osm_row["name"],
                    "latitude": osm_row["latitude"],
                    "longitude": osm_row["longitude"],
                    "tags": osm_row["tags"] if isinstance(osm_row["tags"], dict) else {}  # Ensure tags exist
                })
            elif dist > mismatch_threshold_km:
                different_coordinates.append({
                    "name": wikidata_row["plantLabel"],
                    "wikidata_coords": (wikidata_row["latitude"], wikidata_row["longitude"]),
                    "osm_coords": (osm_row["latitude"], osm_row["longitude"]),
                    "difference_km": round(dist, 3)
                })
    
    # Identify Wikidata power plants missing coordinates
    for _, row in wikidata_missing_coords.iterrows():
        wikidata_missing_coordinates.append({
            "name": row["plantLabel"],
            "location": row.get("location", "Unknown")
        })
    
    # Remove duplicates in missing lists
    missing_in_wikidata = pd.DataFrame(missing_in_wikidata).drop_duplicates(subset=["name"]).to_dict("records")
    different_coordinates = pd.DataFrame(different_coordinates).drop_duplicates(subset=["name"]).to_dict("records")
    wikidata_missing_coordinates = pd.DataFrame(wikidata_missing_coordinates).drop_duplicates(subset=["name"]).to_dict("records")

    return missing_in_wikidata, different_coordinates, wikidata_missing_coordinates


def find_missing_in_osm(wikidata_df, osm_df, max_distance_km, mismatch_threshold_km):
    """
    Identifies power plants that are present in Wikidata but missing in OSM.
    Flags coordinate mismatches beyond a specified threshold.

    Args:
        wikidata_df (pd.DataFrame): The DataFrame of power plants from Wikidata.
        osm_df (pd.DataFrame): The DataFrame of power plants from OpenStreetMap.
        max_distance_km (float): The maximum distance to consider a match (in kilometers).
        mismatch_threshold_km (float): The threshold distance beyond which the coordinates are considered mismatched.

    Returns:
        missing power plants in OSM and coordinate mismatches in OSM.
    """
    missing_in_osm, different_coordinates = [], []

    # Normalize names in both datasets
    wikidata_df["normalized_name"] = wikidata_df["plantLabel"].apply(normalize_name)
    osm_df["normalized_name"] = osm_df["name"].apply(normalize_name)

    # Remove power plants that already exist in OSM by normalized name
    wikidata_filtered = wikidata_df[~wikidata_df["normalized_name"].isin(osm_df["normalized_name"])]

    # Separate remaining entries with and without coordinates
    wikidata_with_coords = wikidata_filtered.dropna(subset=["latitude", "longitude"]).copy()
    osm_with_coords = osm_df.dropna(subset=["latitude", "longitude"]).copy()

    # Check which Wikidata power plants are not present in OSM
    if not wikidata_with_coords.empty and not osm_with_coords.empty:
        osm_tree = KDTree(osm_with_coords[["latitude", "longitude"]].to_numpy())
        distances, indices = osm_tree.query(wikidata_with_coords[["latitude", "longitude"]].to_numpy())

        for i, (dist, index) in enumerate(zip(distances, indices)):
            wikidata_row = wikidata_with_coords.iloc[i]
            osm_row = osm_with_coords.iloc[index]
            
            if dist >= max_distance_km:  # If no close match in OSM, add to missing
                missing_in_osm.append({
                    "name": wikidata_row["plantLabel"],
                    "latitude": wikidata_row["latitude"],
                    "longitude": wikidata_row["longitude"],
                    "wikidata_id": wikidata_row.get("wikidata_id", "Unknown")
                })
            elif dist > mismatch_threshold_km:  # If within max distance but mismatched, flag it
                different_coordinates.append({
                    "name": wikidata_row["plantLabel"],
                    "wikidata_coords": (wikidata_row["latitude"], wikidata_row["longitude"]),
                    "osm_coords": (osm_row["latitude"], osm_row["longitude"]),
                    "difference_km": round(dist, 3)
                })
    
    # Remove duplicates in missing lists
    missing_in_osm = pd.DataFrame(missing_in_osm).drop_duplicates(subset=["name"])
    different_coordinates = pd.DataFrame(different_coordinates).drop_duplicates(subset=["name"]).to_dict("records")

    return missing_in_osm, different_coordinates


def output_files(missing_in_wikidata, different_coordinates, wikidata_missing_coordinates, missing_in_osm, osm_different_coordinates):
    """
    Saves the comparison results to CSV files.

    Args:
        missing_in_wikidata (list): List of missing power plants in Wikidata.
        different_coordinates (list): List of power plants with mismatched coordinates.
        wikidata_missing_coordinates (list): List of Wikidata power plants missing coordinates.
        missing_in_osm (list): List of missing power plants in OSM.
        osm_different_coordinates (list): List of mismatched coordinates in OSM.
    """
    result_dfs = {
        "coordinate_mismatches_missing_wikidata.csv": pd.DataFrame(different_coordinates),
        "missing_in_wikidata.csv": pd.DataFrame(missing_in_wikidata),
        'wikidata_missing_coordinate.csv': pd.DataFrame(wikidata_missing_coordinates),
        "missing_in_osm.csv": pd.DataFrame(missing_in_osm),
        "coordinate_mismatches_missing_osm.csv": pd.DataFrame(osm_different_coordinates)
    }
    
    # Save results to CSV files
    for filename, df in result_dfs.items():
        df.to_csv(filename, index=False)
        print(f"✅ {filename} saved with {len(df)} entries.")
    return 


def generate_geojson_from_missing_osm(missing_in_osm, geojson_filename="missing_in_osm.geojson"):
    """
    Generates a GeoJSON file from missing power plants in OSM and saves it to a file.

    Args:
        missing_in_osm (pd.DataFrame): DataFrame containing missing power plants in OSM.
        geojson_filename (str): The name of the output GeoJSON file.
    """
    geojson = {
        "type": "FeatureCollection",
        "features": []
    }
    
    for _, row in missing_in_osm.iterrows():
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]]
            },
            "properties": {
                "name": row["name"],
                "wikidata_id": row.get("wikidata_id", "Unknown")
            }
        }
        geojson["features"].append(feature)
    
    # Write to GeoJSON file
    with open(geojson_filename, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=4)
    
    print(f"✅ GeoJSON file saved as {geojson_filename}")
    return geojson


def generate_quickstatements_from_missing_wikidata(missing_in_wikidata, output_filename="missing_in_wikidata.qs"):
    """
    Generates QuickStatements to add missing power plants from OSM into Wikidata.

    Args:
        missing_in_wikidata (list): List of missing power plants in Wikidata.
        output_filename (str): The name of the output QuickStatements file.
    """
    if not missing_in_wikidata:
        print("✅ No missing power plants in Wikidata from OSM.")
        return

    try:
        lines = []  # Store QuickStatements entries
        created_count = 0  # Counter for created entries
        
        for row in missing_in_wikidata:
            tags = row.get("tags", {})
            
            if not tags:
                continue  # Skip entries without relevant tags
            
            qs_entry = ["CREATE"]  # Create a new Wikidata item
            
            # Add each tag as a key-value pair
            for key, value in tags.items():
                qs_entry.append(f"LAST\t{key}\t\"{value}\"")
            
            lines.extend(qs_entry)
            created_count += 1  # Increment counter
        
        # Write QuickStatements to file
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        print(f"✅ QuickStatements file saved as {output_filename}")
        print(f"🔹 Created {created_count} structured entries for Wikidata upload.")
        
    except Exception as e:
        print(f"❌ Error generating QuickStatements: {e}")


# ---------------------- Main Execution ---------------------- #

def main():
    """
    Main function that fetches power plant data from Wikidata and OSM,
    compares the datasets, and saves the results in CSV and GeoJSON formats.
    """
    print(f"🔹 Fetching power plant data for {COUNTRY_NAME}...")

    osm_df = fetch_osm_power_plants(COUNTRY_NAME)
    wikidata_df = fetch_wikidata_power_plants(COUNTRY_NAME)

    if osm_df.empty or wikidata_df.empty:
        print("Error: One or both datasets could not be retrieved.")
        return

    print("🔹 Comparing datasets...")

    # Perform the comparison
    missing_in_wikidata, different_coordinates, wikidata_missing_coordinates = compare_osm_to_wikidata(
        osm_df, wikidata_df, max_distance_km, mismatch_threshold_km)

    missing_in_osm, osm_different_coordinates = find_missing_in_osm(
        wikidata_df, osm_df, max_distance_km, mismatch_threshold_km)

    # Output the results
    output_files(missing_in_wikidata, different_coordinates, wikidata_missing_coordinates, missing_in_osm, osm_different_coordinates)
    generate_quickstatements_from_missing_wikidata(missing_in_wikidata)
    generate_geojson_from_missing_osm(missing_in_osm)


if __name__ == "__main__":
    main()
