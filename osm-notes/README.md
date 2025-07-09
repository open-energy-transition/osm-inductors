# OSM Power Infrastructure Notes Importer

A Python tool that downloads OpenStreetMap Notes from entire countries and filters for power infrastructure-related content. Features multilingual keyword detection in all UN official languages (English, Spanish, French, Russian, Chinese, Arabic).

## 🚀 Features

- **Country-wide downloads**: Automatically fetches notes for entire countries using Nominatim API
- **Power infrastructure filtering**: Identifies notes related to power lines, substations, outages, etc.
- **Multilingual support**: Detects power-related keywords in 6 UN official languages
- **Database storage**: Stores filtered notes and comments in PostgreSQL
- **Tile-based processing**: Splits large countries into manageable chunks
- **Rate limiting**: Respects OpenStreetMap API limits
- **Error resilience**: Continues processing despite individual note failures

## 📋 Requirements

### Dependencies
```bash
pip install psycopg lxml requests
```

### Database
- PostgreSQL database (local or cloud)
- Write permissions for table creation

## 🛠️ Installation

1. Clone or download the script:
```bash
git clone repo-link
```

2. Install dependencies:
```bash
pip install psycopg lxml requests
```

3. Configure database connection in the script (edit hardcoded values in `database_connection()` function)

## 🎯 Usage

### Basic Examples

```bash
# Download power infrastructure notes for Colombia
python osm_power_notes.py --country "Colombia" --create-tables

# Download for a specific bounding box
python osm_power_notes.py --bbox "-74.3,-4.8,-74.0,-4.4" --create-tables

# Test with limited tiles
python osm_power_notes.py --country "Germany" --create-tables --max-tiles 5

# List all built-in keywords
python osm_power_notes.py --list-keywords
```

### Advanced Options

```bash
# Custom tile size and rate limiting
python osm_power_notes.py --country "Brazil" \
  --tile-size 0.3 \
  --rate-limit 1.5 \
  --create-tables

# Include more closed notes
python osm_power_notes.py --country "France" \
  --closed 30 \
  --create-tables

# Use custom keywords file
echo -e "smart grid\nmicro grid\ncharging station" > custom_keywords.txt
python osm_power_notes.py --country "Netherlands" \
  --keywords-file custom_keywords.txt \
  --create-tables

# Quiet mode
python osm_power_notes.py --country "Italy" --create-tables --quiet
```

## 📊 Database Schema

The script creates three main tables:

### `notes`
```sql
CREATE TABLE notes (
    id BIGINT PRIMARY KEY,                    -- OSM note ID
    latitude INTEGER NOT NULL,               -- Lat * 10,000,000
    longitude INTEGER NOT NULL,              -- Lon * 10,000,000
    tile BIGINT,                            -- Calculated tile ID
    country VARCHAR(100),                    -- Country name
    created_at TIMESTAMP WITH TIME ZONE,     -- Note creation time
    updated_at TIMESTAMP WITH TIME ZONE,     -- Last update time
    status VARCHAR(20) DEFAULT 'open',       -- open/closed
    closed_at TIMESTAMP WITH TIME ZONE,      -- Closing time
    is_power_related BOOLEAN DEFAULT FALSE,  -- Power infrastructure flag
    power_keywords TEXT[]                    -- Matched keywords
);
```

### `note_comments`
```sql
CREATE TABLE note_comments (
    id SERIAL PRIMARY KEY,
    note_id BIGINT REFERENCES notes(id),
    author_id INTEGER REFERENCES users(id),
    body TEXT,                               -- Comment text
    created_at TIMESTAMP WITH TIME ZONE,
    event VARCHAR(20),                       -- opened/commented/closed
    visible BOOLEAN DEFAULT TRUE
);
```

### `users`
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## 🔍 Querying Data

### Basic Queries

```sql
-- Get all power-related notes
SELECT * FROM notes WHERE is_power_related = true;

-- Count by country
SELECT country, COUNT(*) as power_notes_count 
FROM notes 
WHERE is_power_related = true 
GROUP BY country;

-- Get notes with comments
SELECT n.id, n.country, 
       n.latitude/10000000.0 as lat, 
       n.longitude/10000000.0 as lon,
       array_to_string(n.power_keywords, ', ') as keywords,
       nc.body as comment
FROM notes n
LEFT JOIN note_comments nc ON n.id = nc.note_id
WHERE n.is_power_related = true
ORDER BY n.created_at DESC;
```

### Advanced Queries

```sql
-- Find outages by language
SELECT n.country, COUNT(*) as outage_notes
FROM notes n
JOIN note_comments nc ON n.id = nc.note_id
WHERE n.is_power_related = true
  AND (nc.body ILIKE '%outage%' OR nc.body ILIKE '%apagón%' 
       OR nc.body ILIKE '%panne%' OR nc.body ILIKE '%停电%')
GROUP BY n.country;

-- Most common power keywords
SELECT keyword, COUNT(*) as frequency
FROM notes n, unnest(n.power_keywords) as keyword
WHERE n.is_power_related = true
GROUP BY keyword
ORDER BY frequency DESC
LIMIT 20;

-- Recent power infrastructure activity
SELECT n.id, n.country, n.created_at,
       array_to_string(n.power_keywords, ', ') as keywords
FROM notes n
WHERE n.is_power_related = true 
  AND n.created_at > NOW() - INTERVAL '30 days'
ORDER BY n.created_at DESC;
```

## 🌍 Multilingual Keywords

The script includes power infrastructure terms in:

- 🇺🇸 **English**: power, electricity, substation, outage, transformer...
- 🇪🇸 **Spanish**: energía, electricidad, subestación, apagón, transformador...
- 🇫🇷 **French**: énergie, électricité, sous-station, panne, transformateur...
- 🇷🇺 **Russian**: энергия, электричество, подстанция, авария, трансформатор...
- 🇨🇳 **Chinese**: 电力, 电气, 变电站, 停电, 变压器...
- 🇸🇦 **Arabic**: طاقة, كهرباء, محطة فرعية, انقطاع, محول كهربائي...

Total: **150+** keywords across all languages

## ⚙️ Configuration

### Database Connection
Edit the `database_connection()` function to configure your database:

```python
conn = psycopg.connect(
    host="your-database-host",
    port=5432,
    user="your-username", 
    password="your-password",
    dbname="your-database"
)
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--country` | Country name (e.g., "Germany") | None |
| `--bbox` | Bounding box (min_lon,min_lat,max_lon,max_lat) | None |
| `--tile-size` | Tile size in degrees | 0.5 |
| `--limit` | Notes per tile (max 10,000) | 10,000 |
| `--closed` | Days of closed notes to include | 7 |
| `--rate-limit` | Delay between API calls (seconds) | 1.0 |
| `--max-tiles` | Max tiles to process (testing) | None |
| `--keywords-file` | Custom keywords file | None |
| `--create-tables` | Create database tables | False |
| `--quiet` | Suppress progress output | False |

### Optimization Tips
- Use `--max-tiles` for testing
- Increase `--tile-size` for faster processing (less API calls)
- Decrease `--tile-size` for more reliable processing
- Use `--quiet` to reduce output overhead

## 🚨 Troubleshooting

### Common Issues

**"Database connection error"**
- Check database credentials in script
- Ensure database is running and accessible

**"Could not find bounding box for country"**
- Try alternative country name (e.g., "United Kingdom" vs "UK")
- Use `--bbox` with custom coordinates instead

**"Note missing ID, skipping"**
- Normal for some API responses
- Script continues processing automatically

**"Error fetching from API"**
- Check internet connection
- OSM API may be temporarily unavailable
- Rate limiting may be too aggressive

### Performance Issues

**Slow processing**
- Reduce `--tile-size` (more tiles, smaller requests)
- Increase `--rate-limit` (slower but more reliable)
- Use `--max-tiles` for testing

**Memory usage**
- Script processes tiles individually (low memory)
- Large countries split into manageable chunks

## 📝 Example Countries

```bash
# European countries
python osm_power_notes.py --country "Germany" --create-tables

# American countries  
python osm_power_notes.py --country "Colombia" --create-tables

# Asian countries
python osm_power_notes.py --country "Japan" --create-tables

# African countries
python osm_power_notes.py --country "Kenya" --create-tables
```

## 📊 Data Analysis Examples

### Power Outage Analysis
```sql
-- Countries with most power outage reports
SELECT n.country, COUNT(*) as outage_notes
FROM notes n 
JOIN note_comments nc ON n.id = nc.note_id
WHERE n.is_power_related = true
  AND (nc.body ILIKE '%outage%' OR nc.body ILIKE '%blackout%' 
       OR nc.body ILIKE '%apagón%' OR nc.body ILIKE '%panne%')
GROUP BY n.country
ORDER BY outage_notes DESC;
```

### Infrastructure Mapping Quality
```sql
-- Notes about missing or incorrect power infrastructure
SELECT n.country, COUNT(*) as mapping_issues
FROM notes n
JOIN note_comments nc ON n.id = nc.note_id  
WHERE n.is_power_related = true
  AND (nc.body ILIKE '%missing%' OR nc.body ILIKE '%wrong%'
       OR nc.body ILIKE '%incorrect%' OR nc.body ILIKE '%error%')
GROUP BY n.country;
```

### Language Distribution
```sql
-- Detect note language by keywords
SELECT 
    CASE 
        WHEN array_to_string(power_keywords, ' ') ILIKE '%apagón%' THEN 'Spanish'
        WHEN array_to_string(power_keywords, ' ') ILIKE '%panne%' THEN 'French'  
        WHEN array_to_string(power_keywords, ' ') ILIKE '%停电%' THEN 'Chinese'
        WHEN array_to_string(power_keywords, ' ') ILIKE '%энергия%' THEN 'Russian'
        WHEN array_to_string(power_keywords, ' ') ILIKE '%كهرباء%' THEN 'Arabic'
        ELSE 'English/Other'
    END as detected_language,
    COUNT(*) as note_count
FROM notes 
WHERE is_power_related = true
GROUP BY detected_language;
```

## 🤝 Contributing

### Adding Keywords
Create a text file with one keyword per line:
```
smart grid
energy storage
electric vehicle
charging station
```

Use with: `--keywords-file your_keywords.txt`

### Language Support
To add more languages, edit the `POWER_KEYWORDS` list in the script.

## 🔗 Related Resources

- [OpenStreetMap Notes](https://wiki.openstreetmap.org/wiki/Notes)
- [OSM API Documentation](https://wiki.openstreetmap.org/wiki/API_v0.6)
- [Power Infrastructure Tagging](https://wiki.openstreetmap.org/wiki/Power)
- [Nominatim API](https://nominatim.org/release-docs/develop/api/Overview/)

---