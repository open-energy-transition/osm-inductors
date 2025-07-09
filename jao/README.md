# JAO-OSM Substation Matcher

This tool matches substations from the [JAO Static Grid Model](https://www.jao.eu/sites/default/files/static-grid/) with corresponding OpenStreetMap (OSM) substation entries using string normalization and substring comparison.

## Purpose

The goal is to build a geospatially-aware dataset of transmission substations referenced in JAO's static network model by:

- Extracting substation names from the JAO Excel dataset
- Matching them to OSM ways tagged as `power=substation` using Overpass API data
- Enriching the original dataset with geographic coordinates and OSM IDs
- Generating an Overpass Turbo query to visualize all matched substations

## Required Input

You must manually download the file: 20240916_Core Static Grid Model_for publication.xlsx contained in the zip folder 202409_Core Static Grid Mode_6th release.zip from [JAO Static Grid Model](https://www.jao.eu/static-grid-model) and place it in the **same directory** as the script before execution.    

## Outputs

- `jao_lines_with_coords.csv`: Full enriched JAO line dataset with lat/lon and OSM IDs for each substation
- `matched_substations_osm.csv`: List of matched JAO/OSM substations with OSM ID and coordinates
- `unmatched_substations.csv`: List of JAO substations that could not be matched or found in OSM.
- `overpass_matched_substations.txt`: Overpass Turbo query to view matched substations in OSM.

The `overpass_matched_substations.txt` can be copy and paste in the [Overpass-turbo website](https://overpass-turbo.eu/) to visualize the results in OSM.

## Requirements

- Python 3.8+
- pandas
- requests
- unicodedata
- openpyxl
