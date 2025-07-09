<<<<<<< HEAD
# osm-inductors
This repo gathers several inductors to encourage contribution on OSM on power grids.  
It provides first of all useful logic to process and then outputs any hint useful for contribution.

If you want to contribute or add any new source to this repository, please refer to [CONTRIBUTE.md]

## OpenStreetMap internal inductors
OpenStreetMap already provides a few 

### OSM notes
OpenStreetMap notes may include very useful local information to help others to find missing ifrastructure.

## Open data inductors
Open data can be any suitable source, used wether as hints (not copied into OSM) or even as a source depending on its licence status.

### Power plant matching
Power plants are described in many public data sources and this hint will provide features that should be improved in OSM.  
=======
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
>>>>>>> jao/main
