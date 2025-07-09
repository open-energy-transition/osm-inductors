import os
import json
import requests
import pandas as pd
import yaml
import hashlib
import pickle

# Load configuration
def load_config(path="config.yaml"):
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
    return os.path.join(CACHE_DIR, f"{name}.pkl")

def load_cache(name):
    if RESET_CACHE:
        return None
    path = cache_path(name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

def save_cache(name, data):
    path = cache_path(name)
    with open(path, "wb") as f:
        pickle.dump(data, f)

# Step 1: Fetch counts per country
def fetch_entity_counts(type_qid, type_label, output_dir=""):
    print(f"\nFetching {type_label} counts grouped by country...")
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

    df = df[df["count"] > 0]
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base_name = type_label.lower().replace(" ", "_")
        df.to_csv(os.path.join(output_dir, f"{base_name}_counts_by_country.csv"), index=False)
    return df

# Step 2: Fetch detailed entity data by country
def fetch_entities_by_country(type_qid, type_label, country_qid, country_label):
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
            parts = coordinates.replace("Point(", "").replace(")", "").split()
            if len(parts) == 2:
                lon, lat = float(parts[0]), float(parts[1])

        all_rows.append({
            "country_name": country_label,
            "country_qid": country_qid,
            "entity": item["item"]["value"],
            "label": item.get("itemLabel", {}).get("value", ""),
            "type": type_label,
            "latitude": lat,
            "longitude": lon,
            # "location": item.get("location", {}).get("value", "") #Not considered to avoid duplication in files
        })

    df = pd.DataFrame(all_rows)
    save_cache(cache_name, df)
    return df

# Step 3: Collect data for one type
def collect_entity_data(type_qid, type_label):
    country_counts = fetch_entity_counts(type_qid, type_label)
    all_entities = []

    print(f"Querying {type_label} data country by country...")
    for _, row in country_counts.iterrows():
        country_qid = row["country"].split("/")[-1]
        country_label = row["countryLabel"]
        print(f"  Querying {type_label} in {country_label} ({country_qid})...")
        try:
            df = fetch_entities_by_country(type_qid, type_label, country_qid, country_label)
            df = df.drop_duplicates(subset="entity")
            if not df.empty:
                df.to_csv("pruebaUSA.csv")
                print(f"    {len(df)} entries found.")
                all_entities.append(df)
                # quit()
            else:
                print("    No entries with coordinates.")
        except Exception as e:
            print(f"    Failed to fetch: {e}")

    non_empty = [df for df in all_entities if not df.empty]
    cleaned_non_empty = [df.dropna(axis=1, how="all") for df in non_empty]
    full_df = pd.concat(cleaned_non_empty, ignore_index=True) if cleaned_non_empty else pd.DataFrame()


    df_with_coords = full_df[full_df["latitude"].notna() & full_df["longitude"].notna()]
    df_without_coords = full_df[full_df["latitude"].isna() | full_df["longitude"].isna()]
    return country_counts, full_df, df_with_coords, df_without_coords

# Step 4: Export GeoJSON

def export_geojson_by_country(df_with_coords, country_counts, type_label, type_qid, output_dir):
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

# Main execution
if __name__ == "__main__":
    for type_qid, info in INFRA_TYPES.items():
        type_label = info["label"]
        base_name = type_label.lower().replace(" ", "_")
        folder_name = f"{type_qid}_{base_name}"
        output_dir = os.path.join("output_by_qid", folder_name)
        os.makedirs(output_dir, exist_ok=True)

        summary = fetch_entity_counts(type_qid, type_label, output_dir)
        _, df_all, df_coords, df_missing = collect_entity_data(type_qid, type_label)

        df_all.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_full.csv"), index=False)
        df_coords.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_with_coordinates.csv"), index=False)
        df_missing.to_csv(os.path.join(output_dir, f"wikidata_{base_name}_without_coordinates.csv"), index=False)

        export_geojson_by_country(df_coords, summary, type_label, type_qid, output_dir)
        print(f"\nFinished processing {type_label}")
