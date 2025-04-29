import pandas as pd
import requests
import json
import os

# SPARQL endpoint
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

# Headers for requests
HEADERS = {
    "User-Agent": "SubstationDataCollector/1.0",
    "Accept": "application/sparql-results+json"
}

SUBSTATION_TYPES = {
    "Q174814": "Electrical substation",
    "Q2356943": "HVDC converter station",
    "Q20170565": "HVDC back-to-back station",
    "Q1392266": "Mobile electrical substation",
    "Q1795675": "Substation platform (offshore)"
}

# Step 1: Fetch substation counts grouped by country for each type
def fetch_substation_counts():
    all_rows = []

    for type_qid, type_label in SUBSTATION_TYPES.items():
        print(f"Fetching country counts for {type_label} ({type_qid})...")

        query = f"""
        SELECT ?country ?countryLabel (COUNT(?item) AS ?count) WHERE {{
          ?item wdt:P31 wd:{type_qid}.
          ?item wdt:P17 ?country.
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
        }}
        GROUP BY ?country ?countryLabel
        """

        response = requests.get(WIKIDATA_ENDPOINT, params={"query": query, "format": "json"}, headers=HEADERS, timeout=180)
        response.raise_for_status()
        data = response.json()["results"]["bindings"]

        for item in data:
            all_rows.append({
                "country": item["country"]["value"],
                "countryLabel": item["countryLabel"]["value"],
                "type": type_qid,
                "typeLabel": type_label,
                "count": int(item["count"]["value"])
            })

    df = pd.DataFrame(all_rows)
    df_grouped = df.groupby(["country", "countryLabel"]).agg({
        "count": "sum",
        "typeLabel": lambda x: ', '.join(sorted(set(x)))
    }).reset_index()
    df_grouped = df_grouped.sort_values("count", ascending=False)
    df_grouped.to_csv('groupedbycountry.csv')
    return df_grouped

# Step 2: Fetch detailed substation info per country using offset and limit to avoid server errors
def fetch_substations_by_country(country_qid, country_label):
    all_rows = []
    offset = 0
    limit = 500

    while True:
        query = f"""
        SELECT ?substation ?substationLabel ?typeLabel ?location ?coordinates WHERE {{
          VALUES ?type {{
            wd:Q174814
            wd:Q2356943
            wd:Q20170565
            wd:Q1392266
            wd:Q1795675
          }}
          ?substation wdt:P31 ?type.
          ?substation wdt:P17 wd:{country_qid}.
          OPTIONAL {{ ?substation wdt:P625 ?coordinates. }}
          OPTIONAL {{ ?substation wdt:P276 ?location. }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
        }}
        LIMIT {limit} OFFSET {offset}
        """

        response = requests.get(WIKIDATA_ENDPOINT, params={"query": query, "format": "json"}, headers=HEADERS)
        response.raise_for_status()
        data = response.json()["results"]["bindings"]

        if not data:
            break

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
                "substation": item["substation"]["value"],
                "label": item.get("substationLabel", {}).get("value", ""),
                "type": item.get("typeLabel", {}).get("value", ""),
                "latitude": lat,
                "longitude": lon,
            })

        offset += limit

    return pd.DataFrame(all_rows)

# Step 3: Full process
def collect_substation_data():
    print("Fetching counts by country...")
    country_counts = fetch_substation_counts()

    all_substations = []

    print("Querying substations country by country...")
    for _, row in country_counts.iterrows():
        country_qid = row["country"].split("/")[-1]
        country_label = row["countryLabel"]
        try:
            df = fetch_substations_by_country(country_qid, country_label)
            if not df.empty:
                all_substations.append(df)
        except Exception as e:
            print(f"Failed to fetch for {country_qid}: {e}")

    full_df = pd.concat(all_substations, ignore_index=True)

    # Rows with both latitude and longitude
    df_with_coords = full_df[full_df["latitude"].notna() & full_df["longitude"].notna()]

    # Rows missing either latitude or longitude
    df_without_coords = full_df[full_df["latitude"].isna() | df["longitude"].isna()]

    return full_df, df_with_coords, df_without_coords

def export_geojson_by_country(df_with_coords, output_dir="geojson_by_country"):
    """
    Generates one GeoJSON file per country from substations with coordinates.

    Args:
        df_with_coords (pd.DataFrame): DataFrame with 'country_name', 'latitude', 'longitude', and substation info.
        output_dir (str): Directory where GeoJSON files will be saved.
    """
    os.makedirs(output_dir, exist_ok=True)

    grouped = df_with_coords.groupby("country_name")
    #print(grouped)
    for country, group in grouped:
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
                        "substation": row.get("substation", ""),
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

    print(f"GeoJSON files saved to folder: {output_dir}")

if __name__ == "__main__":
    df_allsubstations, df_with_coords, missing_coordinates = collect_substation_data()
    df_allsubstations.to_csv("wikidata_substations_full.csv", index=False)
    df_with_coords.to_csv("wikidata_substations_with_coordinates.csv", index=False)
    missing_coordinates.to_csv("wikidata_substations_without_coordinates.csv", index=False)
    export_geojson_by_country(df_with_coords, output_dir="geojson_by_country")
    print("Substation data successfully saved to csv files")
    print('geojson files saved')
