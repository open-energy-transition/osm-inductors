import os
import json
import requests
import pandas as pd
import yaml
import hashlib
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed

from collections import defaultdict

#Global variable for all-included dataframe

ALL_COORDINATES_DF = []

# ------------------------
# Configuration & Caching
# ------------------------

def load_config(path="config.yaml"):
    """
    Load project configuration from a YAML file.

    Returns:
        dict: Dictionary containing endpoint, user-agent, cache flags, and infrastructure types.
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
WIKIDATA_ENDPOINT = config["wikidata_endpoint"]
HEADERS = {
    "User-Agent": config["user_agent"],
    "Accept": "application/sparql-results+json"
}
INFRA_TYPES = config["infrastructure_types"]
RESET_CACHE = config.get("reset_cache", False)
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def cache_path(name):
    """
    Construct full file path for a cache file.    
    """
    return os.path.join(CACHE_DIR, f"{name}.pkl")

def load_cache(name):
    """
    Load cache from disk if available and not reset.

    Args:
        name (str): Cache key or filename (without extension).

    Returns:
        Any or None: Loaded object or None if cache miss or disabled.
    """

    if RESET_CACHE:
        return None
    path = cache_path(name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

def save_cache(name, data):
    """
    Persist data object to cache using pickle.

    Args:
        name (str): Cache key or filename (without extension).
        data (Any): Data object to be saved.
    """
    path = cache_path(name)
    with open(path, "wb") as f:
        pickle.dump(data, f)

# -----------------------------
# Step 1: Entity Count by Country
# -----------------------------

def fetch_entity_counts(type_qid, type_label, output_dir=""):
    """
    Query Wikidata for per-country counts of a given infrastructure type (e.g., power plant).

    Args:
        type_qid (str): QID representing the type (e.g., Q159719).
        type_label (str): Human-readable label (e.g., "power plant").
        output_dir (str): Directory to save CSV output.

    Returns:
        pd.DataFrame: DataFrame with columns [country, countryLabel, count].
    """

    print(f"\nGetting {type_label} counts grouped by country...")
    cache_name = f"counts_{type_qid}"
    cached = load_cache(cache_name)
    if cached is not None:
        print("Loaded counts from cache.")
        df = cached
    else:
        all_rows = []
        offset = 0
        limit = 500

        while True:
            query = f"""
            SELECT ?country ?countryLabel (COUNT(DISTINCT ?item) AS ?count) WHERE {{
              ?item wdt:P31/wdt:P279* wd:{type_qid}.
              ?item wdt:P17 ?country.
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
            }}
            GROUP BY ?country ?countryLabel
            ORDER BY DESC(?count)
            OFFSET {offset} LIMIT {limit}
            """
            response = requests.get(WIKIDATA_ENDPOINT, params={"query": query, "format": "json"}, headers=HEADERS, timeout=180)
            response.raise_for_status()
            data = response.json()["results"]["bindings"]
            if not data:
                break

            for item in data:
                all_rows.append({
                    "country": item["country"]["value"],
                    "countryLabel": item["countryLabel"]["value"],
                    "count": int(item["count"]["value"])
                })

            offset += limit

        df = pd.DataFrame(all_rows)
        save_cache(cache_name, df)

    
    # Only proceed if 'count' column exists and is non-empty
    if "count" not in df.columns or df.empty:
        print(f"No count data returned for {type_label} ({type_qid}). Skipping.\n")
        return pd.DataFrame()

    df = df[df["count"] > 0]
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base_name = type_label.lower().replace(" ", "_")
        df.to_csv(os.path.join(output_dir, f"{base_name}_counts_by_country.csv"), index=False)
    return df

# -----------------------------
# Step 2: Fetch Entities per Country
# -----------------------------

def fetch_entities_by_country(type_qid, type_label, country_qid, country_label):

    """
    Fetch detailed entity-level data for a given type and country.

    Args:
        type_qid (str): QID of the infrastructure type.
        type_label (str): Human-readable label.
        country_qid (str): QID of the country.
        country_label (str): Country name.

    Returns:
        pd.DataFrame: Entity data including coordinates if any.
    """

    cache_name = f"entities_{type_qid}_{country_qid}"
    if not RESET_CACHE:
        cached = load_cache(cache_name)
        if cached is not None:
            return cached

    query = f"""
    SELECT DISTINCT ?item ?itemLabel ?location ?coordinates WHERE {{
      ?item wdt:P31/wdt:P279* wd:{type_qid}.
      ?item wdt:P17 wd:{country_qid}.
      OPTIONAL {{ ?item wdt:P625 ?coordinates. }}
      OPTIONAL {{ ?item wdt:P276 ?location. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """

    response = requests.get(WIKIDATA_ENDPOINT, params={"query": query, "format": "json"}, headers=HEADERS)
    response.raise_for_status()
    data = response.json()["results"]["bindings"]

    all_rows = []
    for item in data:
        coordinates = item.get("coordinates", {}).get("value")
        lat, lon = None, None
        if coordinates and coordinates.startswith("Point("):
            try:
                lon_str, lat_str = coordinates.replace("Point(", "").replace(")", "").split()
                lon, lat = float(lon_str), float(lat_str)
            except ValueError:
                pass  # leave lat/lon as None

        all_rows.append({
            "country_name": country_label,
            "country_qid": country_qid,
            "entity": item["item"]["value"],
            "label": item.get("itemLabel", {}).get("value", ""),
            "type": type_label,
            "latitude": lat,
            "longitude": lon,
        })

    df = pd.DataFrame(all_rows)
    save_cache(cache_name, df)
    return df

# --------------------------------
# Step 3: Parallel Entity Fetching
# --------------------------------

def collect_entity_data_parallel(type_qid, type_label):
    """
    Collects all entity data for a given type using per-country parallel processing.

    Args:
        type_qid (str): QID of the infrastructure type.
        type_label (str): Label for output naming.

    Returns:
        tuple: (full_df, df_with_coordinates, df_without_coordinates)
    """

    country_counts = fetch_entity_counts(type_qid, type_label)
    print(f"Querying {type_label} data country by country (parallel)...")

    all_entities = []
    failed_countries = [] # Keep track of failures

    def task(row):
        country_qid = row["country"].split("/")[-1]
        country_label = row["countryLabel"]
        print(f"Querying {type_label} in {country_label} ({country_qid})...")
        try:
            df = fetch_entities_by_country(type_qid, type_label, country_qid, country_label)
            df = df.drop_duplicates(subset="entity")
            print(f"{len(df)} entries found.")
            return df
        except Exception as e:
            print(f"Failed to fetch {country_label}: {e}")
            failed_countries.append((country_label, country_qid, str(e)))
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(task, row): row for _, row in country_counts.iterrows()}
        for future in as_completed(futures):
            result_df = future.result()
            if not result_df.empty:
                all_entities.append(result_df)

    # Show failure summary, if any
    if failed_countries:
        print("\nSummary of countries that failed to fetch:")
        for label, qid, msg in failed_countries:
            print(f" - {label} ({qid}): {msg}")

    non_empty = [df for df in all_entities if not df.empty]
    cleaned_non_empty = [df.dropna(axis=1, how="all") for df in non_empty]
    full_df = pd.concat(cleaned_non_empty, ignore_index=True) if cleaned_non_empty else pd.DataFrame()

    if full_df.empty:
        print(f"No data returned for {type_label} ({type_qid}). Skipping.\n")
        return full_df, pd.DataFrame(), pd.DataFrame()

   
    coord_cols_exist = all(col in full_df.columns for col in ["latitude", "longitude"])
    if coord_cols_exist:
        full_df["latitude"] = pd.to_numeric(full_df["latitude"], errors="coerce")
        full_df["longitude"] = pd.to_numeric(full_df["longitude"], errors="coerce")

        df_coords = full_df[
            full_df["latitude"].notna() &
            full_df["longitude"].notna() &
            full_df["type"].notna()
        ].copy()

        df_without_coords = full_df[~full_df.index.isin(df_coords.index)].copy()
    else:
        print(f"Skipping {type_label} ({type_qid}) due to missing coordinate columns.")
        df_without_coords = full_df.copy()
        return full_df, pd.DataFrame(), df_without_coords


    return full_df, df_coords, df_without_coords

# -----------------------------
# Step 4: Export GeoJSON Outputs
# -----------------------------

def export_geojson_by_country(df_with_coords, country_counts, type_label, type_qid, output_dir):
    """
    Write per-country GeoJSON files for all entities with coordinates.

    Args:
        df_with_coords (pd.DataFrame): Filtered dataset containing coordinates.
        country_counts (pd.DataFrame): Metadata for all countries fetched.
        type_label (str): Infrastructure label.
        type_qid (str): QID used for classification.
        output_dir (str): Folder to write GeoJSON files.
    """
    os.makedirs(output_dir, exist_ok=True)
    grouped = df_with_coords.groupby("country_name")
    generated_files = 0
    countries_with_geojson = set(grouped.groups.keys())
    all_countries = set(country_counts["countryLabel"].tolist())

    for country, group in grouped:
        features = []
        for _, row in group.iterrows():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["longitude"], row["latitude"]]
                },
                "properties": {
                    "label": row.get("label", ""),
                    "type": row.get("type", ""),
                    "entity": row.get("entity", ""),
                    "country_qid": row.get("country_qid", "")
                }
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        safe_filename = country.replace("/", "_").replace("\\", "_").replace(" ", "_")
        filepath = os.path.join(output_dir, f"{safe_filename}.geojson")

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)


        generated_files += 1

    print(f"\n{type_label}: {generated_files} GeoJSON files saved to '{output_dir}'")
    if generated_files != country_counts.shape[0]:
        print(f"Warning: {country_counts.shape[0]} countries counted, but only {generated_files} GeoJSON files created.")
        missing_geojson = sorted(all_countries - countries_with_geojson)
        print("Countries with no GeoJSON (missing coordinates):")
        for country in missing_geojson:
            print(f" - {country}")


def process_infrastructure_type(type_qid, type_label, version="v2"):
    """
    Executes the full data retrieval and export workflow for a given infrastructure type.
    
    Args:
        type_qid (str): Wikidata QID for the infrastructure type.
        type_label (str): Human-readable label for the infrastructure type.
        version (str): Version label for the output directory structure (e.g., 'v2').
    """
    base_name = type_label.lower().replace(" ", "_")
    folder_name = f"{type_qid}_{base_name}"
    output_dir = os.path.join("output_by_qid_v2", folder_name)
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Fetch per-country counts
    summary = fetch_entity_counts(type_qid, type_label, output_dir)

    if summary.empty:
        print(f"No count data returned for {type_label} ({type_qid}). Skipping.\n")
        return

    os.makedirs(output_dir, exist_ok=True)

    # Step 2: Fetch entities using parallel country-level calls
    df_all, df_coords, df_missing = collect_entity_data_parallel(type_qid, type_label)

    if df_all.empty:
        print(f"No entity data returned for {type_label} ({type_qid}). Skipping.\n")
        return

    # Step 3: Save all results to CSV
    df_all.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_full.csv"), index=False)
    df_coords.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_with_coordinates.csv"), index=False)
    df_missing.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_without_coordinates.csv"), index=False)

    if df_coords.empty:
        print(f"No coordinate data for {type_label} ({type_qid}). GeoJSON not created.\n")
        return

    ALL_COORDINATES_DF.append(df_coords.copy())

    # Step 4: Export GeoJSON
    export_geojson_by_country(df_coords, summary, type_label, type_qid, output_dir)

    print(f"\nFinished processing {type_label}")


def generate_combined_geojson_by_country(df_list, output_root="output_by_qid_v2"):
    """
    Combines all per-QID coordinate dataframes, removes duplicates, and generates a merged 
    CSV and per-country GeoJSON files containing all infrastructure types.

    Args:
        df_list (list): List of pd.DataFrame objects (df_coords) from each QID run.
        output_root (str): Root directory to store the output files.
    """
    if not df_list:
        print("No coordinate data found across all QIDs. Nothing to merge.")
        return

    print("\nMerging all coordinate dataframes from all QIDs...")
    combined_df = pd.concat(df_list, ignore_index=True)
    combined_df = combined_df.drop_duplicates(subset="entity")

    # Save combined CSV
    csv_path = os.path.join(output_root, "wikidata_all_qids_with_coordinates.csv")
    combined_df.to_csv(csv_path, index=False)
    print(f"Combined CSV saved at {csv_path}")

    # Generate per-country GeoJSONs
    print("Generating merged GeoJSONs by country...")
    geojson_dir = os.path.join(output_root, "geojson_by_country")
    os.makedirs(geojson_dir, exist_ok=True)

    for country, group in combined_df.groupby("country_name"):
        features = []
        for _, row in group.iterrows():
            if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row["longitude"], row["latitude"]]
                    },
                    "properties": {
                        "label": row.get("label", ""),
                        "type": row.get("type", ""),
                        "entity": row.get("entity", ""),
                        "country_qid": row.get("country_qid", ""),
                    }
                })

        if features:
            geojson = {
                "type": "FeatureCollection",
                "features": features
            }
            safe_filename = country.replace("/", "_").replace("\\", "_").replace(" ", "_")
            filepath = os.path.join(geojson_dir, f"{safe_filename}.geojson")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"\nAggregated country GeoJSONs saved to: {geojson_dir}")



# -----------------------------
# Main Execution
# -----------------------------
if __name__ == "__main__":
    for type_qid, info in INFRA_TYPES.items():
        process_infrastructure_type(type_qid, info["label"])

    generate_combined_geojson_by_country(ALL_COORDINATES_DF)
    print('Qid processing ended successfuly')
