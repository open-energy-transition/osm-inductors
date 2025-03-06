# OSM vs Wikidata Power Plant Comparison

This Python script compares power plant data between **OpenStreetMap (OSM)** and **Wikidata**. It fetches data from both sources using APIs, performs comparisons based on geographic proximity and name, and identifies missing power plants or coordinate mismatches. The comparison results are saved in **CSV** and **GeoJSON** formats.

**Note**: This project is **under construction**. The script currently compares power plants, but it can be modified to fetch and compare substations instead by changing the instances in the fetch_wikidata_power_plants functions in the **Wikidata SPARQL query** and the **node, way, and relation** in the **OSM Overpass API query** inside the fetch_osm_power_plants 

## Features
- Fetches power plant data from Wikidata using the SPARQL API.
- Fetches power plant data from OpenStreetMap using the Overpass API.
- Compares the datasets based on geographic proximity and name matching.
- Identifies missing power plants and coordinate mismatches between OSM and Wikidata.
- Outputs the comparison results in CSV files, geoJSON file for missing data in OSM and quickstatement file for missing data in wikidata

## CSV Files Output
The script generates the following CSV files containing valuable comparison data:
- **`wikidataset.csv`**: Contains the power plants fetched from Wikidata.
- **`osm_api_dataset.csv`**: Contains the power plants fetched from OpenStreetMap.
- **Comparison Results CSV Files**:
  - **`missing_in_wikidata.csv`**: Lists power plants missing in Wikidata but found in OSM.
  - **`coordinate_mismatches_missing_wikidata.csv`**: Lists coordinate mismatches in Wikidata.
  - **`wikidata_missing_coordinate.csv`**: Lists Wikidata entries missing coordinates.
  - **`missing_in_osm.csv`**: Lists power plants missing in OpenStreetMap but found in wikidata.
  - **`coordinate_mismatches_missing_osm.csv`**: Lists coordinate mismatches in the missing data from OpenStreetMap.

## Requirements
To run this script, you need the following Python libraries:
- pandas
- requests
- geopy
- fuzzywuzzy
- scipy
- numpy

You can install all dependencies by running:

pip install -r requirements.txt

## Usage
To run the script, use the following command: python compare_osm_wikidata_v3.py

The script will:
1. Fetch data from both OpenStreetMap and Wikidata.
2. Compare the datasets based on name and location.
3. Generate the comparison results in CSV files as described above.
4. Generate GeoJSON file of missing powerplants in OSM.
5. Generate a Quickstatement file with missing powerplant data in wikidata.
