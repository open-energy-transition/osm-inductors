import os
import re
import pandas as pd
import requests
import unicodedata

# ---------------------- Utility Functions ----------------------

def normalize(text):
    """
    Normalize strings by removing accents, punctuation, and converting to lowercase.
    """
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ASCII', 'ignore').decode()
    text = re.sub(r'[^\w\s]', '', text)
    return text.lower().strip()

# ---------------------- Data Loading ----------------------

def load_jao_dataset(filepath):
    """
    Load and clean the JAO Excel dataset. Rename substation columns for clarity.
    """
    print("Loading JAO dataset...")
    xls = pd.ExcelFile(filepath)
    df = xls.parse("Lines")
    df.columns = df.iloc[0]
    df = df.drop(df.index[0]).reset_index(drop=True)
    df.columns.values[3] = "Substation_1"
    df.columns.values[4] = "Substation_2"
    return df

def extract_unique_substations(df):
    """
    Extract a list of unique substation names from both sides of each connection.
    """
    substations = pd.unique(pd.concat([df["Substation_1"], df["Substation_2"]]).dropna()).tolist()
    print(f"Found {len(substations)} unique substations in JAO.")
    return substations

def load_osm_substations_from_csv(csv_path="osm_europe_substations.csv"):
    """
    Load pre-fetched OSM substation data from local CSV.
    """
    print(f"Loading OSM substations from '{csv_path}'...")
    return pd.read_csv(csv_path)

# ---------------------- OSM Data Collection ----------------------

def fetch_and_save_osm_substations(output_csv="osm_europe_substations.csv"):
    """
    Fetch all substations in Central/Eastern Europe from Overpass API and save to CSV.
    """
    print("Querying Overpass API for substations in Europe...")
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = """
    [out:json][timeout:300];
    way["power"="substation"](43.0, -1.0, 55.5, 25.0);
    out tags center;
    """
    response = requests.post(
        overpass_url, data=query.encode("utf-8"),
        headers={"User-Agent": "JAOMapperBot/1.0"}, timeout=300
    )
    response.raise_for_status()
    data = response.json()

    records = [
        {
            "osm_id": el["id"],
            "osm_name": el.get("tags", {}).get("name", "").strip(),
            "latitude": el.get("center", {}).get("lat"),
            "longitude": el.get("center", {}).get("lon")
        }
        for el in data.get("elements", [])
        if el.get("tags", {}).get("name")
    ]

    df_osm = pd.DataFrame(records)
    df_osm.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Retrieved {len(records)} substations and saved to '{output_csv}'")
    return df_osm

# ---------------------- Matching Logic ----------------------

def build_substation_coordinate_map(substation_names, osm_df):
    """
    Match JAO substations to OSM substations using normalized substring comparison.
    """
    print("Starting matching process...")
    osm_df["normalized_osm_name"] = osm_df["osm_name"].apply(normalize)
    
    match_dict, match_list, unmatched_list = {}, [], []

    for name in substation_names:
        normalized_name = normalize(name)
        match = osm_df[osm_df["normalized_osm_name"].str.contains(normalized_name, na=False)]
        
        if not match.empty:
            row = match.iloc[0]
            match_dict[name] = {"lat": row["latitude"], "lon": row["longitude"], "osm_id": row["osm_id"]}
            match_list.append({
                "jao_substation": name,
                "matched_osm_name": row["osm_name"],
                "osm_id": row["osm_id"],
                "latitude": row["latitude"],
                "longitude": row["longitude"]
            })
        else:
            match_dict[name] = {"lat": None, "lon": None, "osm_id": None}
            unmatched_list.append({"jao_substation": name})

    print(f"Matched: {len(match_list)} | Unmatched: {len(unmatched_list)}")
    return match_dict, pd.DataFrame(match_list), pd.DataFrame(unmatched_list)

# ---------------------- Data Enrichment ----------------------

def enrich_jao_with_coords(df, coord_map):
    """
    Append OSM coordinates and IDs to the original JAO DataFrame.
    """
    for suffix in ["1", "2"]:
        df[f"Substation_{suffix}_lat"] = df[f"Substation_{suffix}"].map(lambda x: coord_map.get(x, {}).get("lat"))
        df[f"Substation_{suffix}_lon"] = df[f"Substation_{suffix}"].map(lambda x: coord_map.get(x, {}).get("lon"))
        df[f"Substation_{suffix}_id"]  = df[f"Substation_{suffix}"].map(lambda x: coord_map.get(x, {}).get("osm_id"))
    return df

# ---------------------- Overpass Query Builder ----------------------

def build_overpass_query(matched_df):
    """
    Create an Overpass Turbo query to fetch matched substations by ID.
    """
    osm_ids = matched_df["osm_id"].dropna().unique().astype(int).tolist()
    query = "[out:json][timeout:120];\n(\n"
    query += "".join([f"  way({osm_id});\n" for osm_id in osm_ids])
    query += ");\nout body center;"
    return query

# ---------------------- Main Script ----------------------

if __name__ == "__main__":
    jao_file = "20240916_Core Static Grid Model_for publication.xlsx"

    # Step 1: Load JAO and extract substations
    df_jao = load_jao_dataset(jao_file)
    unique_substations = extract_unique_substations(df_jao)

    # Step 2: Load or fetch OSM substations
    osm_csv = "osm_europe_substations.csv"
    osm_df = load_osm_substations_from_csv(osm_csv) if os.path.exists(osm_csv) else fetch_and_save_osm_substations(osm_csv)

    # Step 3: Match and map substations
    coord_map, matched_df, unmatched_df = build_substation_coordinate_map(unique_substations, osm_df)

    # Step 4: Save results
    matched_df.to_csv("matched_substations_osm.csv", index=False, encoding="utf-8-sig")
    unmatched_df.to_csv("unmatched_substations.csv", index=False, encoding="utf-8-sig")

    # Step 5: Enrich original dataset and export
    enriched_df = enrich_jao_with_coords(df_jao, coord_map)
    enriched_df.to_csv("jao_lines_with_coords.csv", index=False, encoding="utf-8-sig")

    # Step 6: Build Overpass Turbo query
    overpass_query = build_overpass_query(matched_df)
    with open("overpass_matched_substations.txt", "w", encoding="utf-8") as f:
        f.write(overpass_query)

    # Step 7: Summary
    print("\nSummary")
    print(f"- Total unique substations in JAO: {len(unique_substations)}")
    print(f"- Matched with OSM: {len(matched_df)}")
    print(f"- Unmatched: {len(unmatched_df)}")
    assert len(unique_substations) == len(matched_df) + len(unmatched_df), "Substation count mismatch"

    print("\nFiles generated:")
    print("- jao_lines_with_coords.csv")
    print("- matched_substations_osm.csv")
    print("- unmatched_substations.csv")
    print("- overpass_matched_substations.txt")

