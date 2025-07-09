#!/usr/bin/env python3
"""
OSM Power Infrastructure Notes Importer

Downloads OSM Notes from OpenStreetMap API and filters for power infrastructure-related content.
Supports entire countries with multilingual keyword detection in UN official languages.
"""

import argparse
import sys
import time
import math
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Tuple, List
from urllib.parse import urlencode

import psycopg
import requests
from lxml import etree


POWER_KEYWORDS = [
    # English
    'power', 'electricity', 'electric', 'electrical', 'energy', 'utility',
    'substation', 'transformer', 'transmission', 'distribution',
    'power line', 'power lines', 'powerline', 'powerlines',
    'overhead line', 'overhead lines', 'underground cable',
    'utility pole', 'power pole', 'electricity pole',
    'pylon', 'tower', 'transmission tower', 'power tower',
    'grid', 'power grid', 'electrical grid', 'supply', 'power supply',
    'voltage', 'high voltage', 'low voltage', 'medium voltage',
    'kV', 'kv', 'kilovolt', 'volt',
    'outage', 'blackout', 'power cut', 'no power', 'power failure',
    'power down', 'electricity cut', 'power restoration',
    'generator', 'solar panel', 'wind turbine', 'power station',
    'power plant', 'electrical cabinet', 'switch gear', 'switchgear',
    'meter', 'power meter', 'electricity meter',
    
    # Spanish
    'energía', 'electricidad', 'eléctrico', 'eléctrica', 'energético',
    'servicio público', 'utilidad', 'corriente',
    'subestación', 'transformador', 'transmisión', 'distribución',
    'línea eléctrica', 'líneas eléctricas', 'línea de transmisión',
    'cable subterráneo', 'cable aéreo', 'tendido eléctrico',
    'poste eléctrico', 'poste de luz', 'torre eléctrica',
    'pilón', 'torre de transmisión',
    'red eléctrica', 'red de distribución', 'suministro eléctrico',
    'voltaje', 'tensión', 'alto voltaje', 'bajo voltaje',
    'kilovoltio', 'voltio',
    'apagón', 'corte de luz', 'falla eléctrica', 'sin electricidad',
    'interrupción eléctrica', 'restauración eléctrica',
    'generador', 'panel solar', 'turbina eólica', 'central eléctrica',
    'planta eléctrica', 'gabinete eléctrico', 'contador eléctrico',
    
    # French
    'énergie', 'électricité', 'électrique', 'énergétique',
    'service public', 'utilité', 'courant électrique',
    'sous-station', 'transformateur', 'transmission', 'distribution',
    'ligne électrique', 'lignes électriques', 'ligne de transmission',
    'câble souterrain', 'câble aérien', 'réseau électrique',
    'poteau électrique', 'pylône', 'tour électrique',
    'tour de transmission',
    'réseau électrique', 'alimentation électrique', 'approvisionnement',
    'tension', 'voltage', 'haute tension', 'basse tension',
    'kilovolt', 'volt',
    'panne électrique', 'coupure de courant', 'panne de courant',
    'interruption électrique', 'rétablissement électrique',
    'générateur', 'panneau solaire', 'éolienne', 'centrale électrique',
    'station électrique', 'armoire électrique', 'compteur électrique',
    
    # Russian
    'энергия', 'электричество', 'электрический', 'электрическая',
    'энергетический', 'коммунальное хозяйство', 'ток',
    'подстанция', 'трансформатор', 'передача', 'распределение',
    'линия электропередач', 'ЛЭП', 'воздушная линия',
    'подземный кабель', 'опора ЛЭП', 'столб', 'мачта',
    'башня передачи', 'электрическая вышка',
    'электросеть', 'энергосеть', 'электроснабжение',
    'напряжение', 'высокое напряжение', 'низкое напряжение',
    'киловольт', 'вольт',
    'отключение электричества', 'авария на сети', 'нет света',
    'перебои с электричеством', 'восстановление электроснабжения',
    'генератор', 'солнечная батарея', 'ветрогенератор',
    'электростанция', 'электрощит', 'счётчик электроэнергии',
    
    # Chinese
    '电力', '电能', '电气', '能源', '公用事业', '电流',
    '变电站', '变压器', '输电', '配电', '电力线',
    '输电线路', '架空线路', '地下电缆', '电线杆',
    '输电塔', '电力塔', '铁塔',
    '电网', '供电网络', '电力供应', '供电',
    '电压', '高压', '低压', '中压', '千伏', '伏特',
    '停电', '断电', '电力故障', '没电', '电力中断',
    '供电恢复', '电力恢复',
    '发电机', '太阳能板', '风力发电机', '发电站',
    '电厂', '配电柜', '电表',
    
    # Arabic
    'طاقة', 'كهرباء', 'كهربائي', 'كهربائية', 'طاقوي',
    'مرافق عامة', 'تيار كهربائي', 'قدرة كهربائية',
    'محطة فرعية', 'محول كهربائي', 'نقل الكهرباء', 'توزيع الكهرباء',
    'خط كهربائي', 'خطوط كهربائية', 'خط نقل الكهرباء',
    'كابل تحت الأرض', 'كابل علوي', 'عمود كهربائي',
    'برج كهربائي', 'برج نقل الكهرباء',
    'شبكة كهربائية', 'إمداد كهربائي', 'تموين كهربائي',
    'جهد كهربائي', 'فولتية', 'جهد عالي', 'جهد منخفض',
    'كيلو فولت', 'فولت',
    'انقطاع الكهرباء', 'عطل كهربائي', 'بدون كهرباء',
    'انقطاع التيار', 'استعادة الكهرباء',
    'مولد كهربائي', 'لوحة شمسية', 'توربين رياح',
    'محطة كهرباء', 'خزانة كهربائية', 'عداد كهربائي',
    
    # Technical terms
    'power=', 'generator:', 'cable=', 'voltage=', 'frequency=',
    'kva', 'mva', 'gva', 'hz', 'hertz', 'ampere', 'amp',
    'watt', 'kilowatt', 'megawatt', 'gigawatt',
    'three phase', 'single phase', 'ac', 'dc',
    'alternating current', 'direct current',
    'maintenance', 'repair', 'installation', 'upgrade',
    'mantenimiento', 'reparación', 'instalación', 'mejora',
    'entretien', 'réparation', 'installation', 'amélioration',
    'обслуживание', 'ремонт', 'установка', 'модернизация',
    '维护', '维修', '安装', '升级',
    'صيانة', 'إصلاح', 'تركيب', 'ترقية',
]


@contextmanager
def database_connection(host: str, port: int, user: str, password: str, database: str):
    """Database connection context manager."""
    conn = None
    try:
        conn = psycopg.connect(
            host="your-database-host",
            port=5432,
            user="your-username",
            password="your-password",
            dbname="your-database",
            autocommit=False
        )
        yield conn
    except psycopg.Error as e:
        print(f"Database connection error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn:
            conn.close()


def create_tables_if_not_exist(conn) -> None:
    """Create database tables and perform schema migrations."""
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                display_name VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id BIGINT PRIMARY KEY,
                latitude INTEGER NOT NULL,
                longitude INTEGER NOT NULL,
                tile BIGINT,
                country VARCHAR(100),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                closed_at TIMESTAMP WITH TIME ZONE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS note_comments (
                id SERIAL PRIMARY KEY,
                note_id BIGINT NOT NULL REFERENCES notes(id),
                author_id INTEGER REFERENCES users(id),
                body TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                event VARCHAR(20) NOT NULL,
                visible BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Add missing columns
        for column, definition in [
            ('country', 'VARCHAR(100)'),
            ('is_power_related', 'BOOLEAN DEFAULT FALSE'),
            ('power_keywords', 'TEXT[]')
        ]:
            try:
                cursor.execute(f"ALTER TABLE notes ADD COLUMN IF NOT EXISTS {column} {definition}")
            except psycopg.Error:
                pass
        
        # Create indexes
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at)',
            'CREATE INDEX IF NOT EXISTS idx_notes_power_related ON notes(is_power_related)',
            'CREATE INDEX IF NOT EXISTS idx_notes_country ON notes(country)',
            'CREATE INDEX IF NOT EXISTS idx_note_comments_note_id ON note_comments(note_id)',
            'CREATE INDEX IF NOT EXISTS idx_users_display_name ON users(display_name)',
        ]
        
        for index in indexes:
            cursor.execute(index)
        
        conn.commit()


def get_country_bbox(country_name: str) -> Optional[str]:
    """Get bounding box for a country using Nominatim API."""
    nominatim_url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': country_name,
        'format': 'json',
        'limit': 1,
        'addressdetails': 1,
        'polygon_geojson': 0
    }
    
    headers = {'User-Agent': 'OSM Power Infrastructure Notes Importer/1.0'}
    
    try:
        response = requests.get(nominatim_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if not data:
            return None
        
        result = data[0]
        bbox = result.get('boundingbox')
        if bbox:
            return f"{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]}"
        
    except Exception as e:
        print(f"Error getting country bbox: {e}", file=sys.stderr)
    
    return None


def split_bbox_into_tiles(bbox_str: str, max_tile_size: float = 1.0) -> List[str]:
    """Split large bounding box into smaller tiles."""
    min_lon, min_lat, max_lon, max_lat = map(float, bbox_str.split(','))
    
    lon_diff = max_lon - min_lon
    lat_diff = max_lat - min_lat
    
    lon_tiles = max(1, math.ceil(lon_diff / max_tile_size))
    lat_tiles = max(1, math.ceil(lat_diff / max_tile_size))
    
    tiles = []
    
    for i in range(lon_tiles):
        for j in range(lat_tiles):
            tile_min_lon = min_lon + (i * lon_diff / lon_tiles)
            tile_max_lon = min_lon + ((i + 1) * lon_diff / lon_tiles)
            tile_min_lat = min_lat + (j * lat_diff / lat_tiles)
            tile_max_lat = min_lat + ((j + 1) * lat_diff / lat_tiles)
            
            tile_bbox = f"{tile_min_lon:.6f},{tile_min_lat:.6f},{tile_max_lon:.6f},{tile_max_lat:.6f}"
            tiles.append(tile_bbox)
    
    return tiles


def is_power_related(note_elem: etree.Element, keywords: List[str]) -> Tuple[bool, List[str]]:
    """Check if a note contains power infrastructure keywords."""
    found_keywords = []
    text_to_check = []
    
    comments_container = note_elem.find('comments')
    if comments_container is not None:
        for comment in comments_container.findall('comment'):
            text_elem = comment.find('text')
            if text_elem is not None and text_elem.text:
                text_to_check.append(text_elem.text.lower())
    
    full_text = ' '.join(text_to_check)
    
    for keyword in keywords:
        if keyword.lower() in full_text:
            found_keywords.append(keyword)
    
    return len(found_keywords) > 0, found_keywords


def get_or_create_user(cursor, display_name: str) -> int:
    """Get user ID or create new user."""
    if not display_name:
        return None
    
    cursor.execute("SELECT id FROM users WHERE display_name = %s", [display_name])
    result = cursor.fetchone()
    
    if result:
        return result[0]
    
    cursor.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        [display_name]
    )
    return cursor.fetchone()[0]


def parse_datetime(datetime_str: str) -> datetime:
    """Parse datetime string in various formats."""
    formats = [
        lambda s: datetime.fromisoformat(s.replace('Z', '+00:00')),
        lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=None),
        lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=None),
        lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=None),
        lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=None),
    ]
    
    for fmt in formats:
        try:
            return fmt(datetime_str)
        except ValueError:
            continue
    
    raise ValueError(f"Unable to parse datetime: {datetime_str}")


def calculate_tile_id(lat: float, lon: float, zoom: int = 16) -> int:
    """Calculate tile ID from coordinates."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (zoom << 28) | (x << 14) | y


def insert_note(cursor, note_elem: etree.Element, keywords: List[str], country: str = None) -> bool:
    """Insert note and comments into database."""
    note_id_elem = note_elem.find('id')
    created_at_elem = note_elem.find('date_created')
    lat_str = note_elem.get('lat')
    lon_str = note_elem.get('lon')
    
    # Validate required fields
    if not all([note_id_elem is not None and note_id_elem.text,
                lat_str, lon_str,
                created_at_elem is not None and created_at_elem.text]):
        return None
    
    try:
        note_id = int(note_id_elem.text)
        lat = float(lat_str)
        lon = float(lon_str)
        created_at = parse_datetime(created_at_elem.text)
    except (ValueError, TypeError):
        return None
    
    tile_id = calculate_tile_id(lat, lon)
    is_power, found_keywords = is_power_related(note_elem, keywords)
    
    latitude_int = int(lat * 10000000)
    longitude_int = int(lon * 10000000)
    
    status_elem = note_elem.find('status')
    status = status_elem.text if status_elem is not None else 'open'
    
    closed_at = None
    if status == 'closed':
        comments_container = note_elem.find('comments')
        if comments_container is not None:
            closed_comments = [c for c in comments_container.findall('comment') 
                             if c.find('action') is not None and c.find('action').text == 'closed']
            if closed_comments:
                last_closed = closed_comments[-1]
                date_elem = last_closed.find('date')
                if date_elem is not None:
                    try:
                        closed_at = parse_datetime(date_elem.text)
                    except:
                        pass
    
    updated_at = created_at
    
    # Insert or update note
    cursor.execute("SELECT id FROM notes WHERE id = %s", [note_id])
    note_exists = cursor.fetchone() is not None
    
    if note_exists:
        cursor.execute("""
            UPDATE notes 
            SET latitude = %s, longitude = %s, tile = %s, country = %s, updated_at = %s, 
                status = %s, closed_at = %s, is_power_related = %s, power_keywords = %s
            WHERE id = %s
        """, [latitude_int, longitude_int, tile_id, country, updated_at, status, closed_at, is_power, found_keywords, note_id])
        
        cursor.execute("DELETE FROM note_comments WHERE note_id = %s", [note_id])
    else:
        cursor.execute("""
            INSERT INTO notes (id, latitude, longitude, tile, country, created_at, updated_at, status, closed_at, is_power_related, power_keywords)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [note_id, latitude_int, longitude_int, tile_id, country, created_at, updated_at, status, closed_at, is_power, found_keywords])
    
    # Insert comments
    comments_container = note_elem.find('comments')
    if comments_container is not None:
        for comment_elem in comments_container.findall('comment'):
            action_elem = comment_elem.find('action')
            date_elem = comment_elem.find('date')
            uid_elem = comment_elem.find('uid')
            user_elem = comment_elem.find('user')
            text_elem = comment_elem.find('text')
            
            if date_elem is None or not date_elem.text:
                continue
            
            try:
                timestamp = parse_datetime(date_elem.text)
            except (ValueError, TypeError):
                continue
            
            action = action_elem.text if action_elem is not None else 'commented'
            body = text_elem.text if text_elem is not None else ''
            
            author_id = None
            if uid_elem is not None and user_elem is not None and uid_elem.text and user_elem.text:
                try:
                    author_id = get_or_create_user(cursor, user_elem.text)
                except Exception:
                    pass
            
            cursor.execute("""
                INSERT INTO note_comments (note_id, author_id, body, created_at, event, visible)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [note_id, author_id, body, timestamp, action, True])
            
            if timestamp > updated_at:
                updated_at = timestamp
    
    cursor.execute("UPDATE notes SET updated_at = %s WHERE id = %s", [updated_at, note_id])
    
    return is_power


def fetch_notes_from_api(bbox: str, limit: int = 100, closed: int = 7,
                        user_agent: str = "OSM Power Infrastructure Notes Importer/1.0") -> List[etree.Element]:
    """Fetch notes from OSM API."""
    base_url = "https://api.openstreetmap.org/api/0.6/notes.xml"
    
    params = {
        'bbox': bbox,
        'limit': min(limit, 10000),
        'closed': closed
    }
    
    headers = {'User-Agent': user_agent}
    url = base_url + '?' + urlencode(params)
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        root = etree.fromstring(response.content)
        notes = root.xpath('.//note')
        
        return notes
        
    except requests.RequestException as e:
        print(f"Error fetching from API: {e}", file=sys.stderr)
        return []
    except etree.XMLSyntaxError as e:
        print(f"Error parsing API response: {e}", file=sys.stderr)
        return []


def import_country_power_notes(args: argparse.Namespace) -> None:
    """Main import function."""
    keywords = POWER_KEYWORDS.copy()
    if args.keywords_file:
        try:
            with open(args.keywords_file, 'r') as f:
                custom_keywords = [line.strip() for line in f if line.strip()]
                keywords.extend(custom_keywords)
            print(f"Loaded {len(custom_keywords)} custom keywords")
        except Exception as e:
            print(f"Error loading keywords file: {e}", file=sys.stderr)
    
    if args.country:
        if not args.quiet:
            print(f"Looking up bounding box for: {args.country}")
        
        country_bbox = get_country_bbox(args.country)
        if not country_bbox:
            print(f"Could not find bounding box for country: {args.country}", file=sys.stderr)
            sys.exit(1)
        
        print(f"Country bounding box: {country_bbox}")
        tiles = split_bbox_into_tiles(country_bbox, args.tile_size)
        print(f"Split into {len(tiles)} tiles for processing")
        
    elif args.bbox:
        tiles = split_bbox_into_tiles(args.bbox, args.tile_size)
    else:
        print("Error: Must specify either --country or --bbox", file=sys.stderr)
        sys.exit(1)
    
    with database_connection(None, None, None, None, None) as conn:
        if args.create_tables:
            if not args.quiet:
                print("Creating database tables...")
            create_tables_if_not_exist(conn)
        
        total_notes = 0
        power_notes = 0
        processed_tiles = 0
        
        with conn.cursor() as cursor:
            for i, tile_bbox in enumerate(tiles):
                if args.max_tiles and i >= args.max_tiles:
                    print(f"Reached max tiles limit ({args.max_tiles}), stopping.")
                    break
                    
                if not args.quiet:
                    print(f"\nProcessing tile {i+1}/{len(tiles)}: {tile_bbox}")
                
                if i > 0:
                    time.sleep(args.rate_limit)
                
                notes = fetch_notes_from_api(
                    bbox=tile_bbox,
                    limit=args.limit,
                    closed=args.closed,
                    user_agent=args.user_agent
                )
                
                if not notes:
                    continue
                
                tile_total = len(notes)
                tile_power = 0
                
                for note_elem in notes:
                    try:
                        result = insert_note(cursor, note_elem, keywords, getattr(args, 'country', None))
                        
                        if result is not None:
                            total_notes += 1
                            if result:
                                tile_power += 1
                                power_notes += 1
                            
                            if not args.quiet and total_notes % 100 == 0:
                                note_id = note_elem.get('id', 'unknown')
                                print(f"  Processed note {note_id} (Total: {total_notes}, Power: {power_notes})")
                            
                            if (total_notes % 100 == 0):
                                conn.commit()
                        
                    except Exception as e:
                        conn.rollback()
                        
                        note_id = note_elem.get('id', 'unknown')
                        if note_id == 'unknown':
                            id_elem = note_elem.find('id')
                            if id_elem is not None:
                                note_id = id_elem.text or 'unknown'
                        
                        print(f"Error processing note {note_id}: {e}", file=sys.stderr)
                        
                        if args.stop_on_error:
                            sys.exit(1)
                        else:
                            continue
                
                processed_tiles += 1
                if not args.quiet:
                    print(f"  Tile completed: {tile_total} notes, {tile_power} power-related")
                
                conn.commit()
        
        if not args.quiet:
            print(f"\n" + "="*50)
            print(f"IMPORT COMPLETED")
            print(f"="*50)
            print(f"Country/Area: {getattr(args, 'country', None) or 'Custom bbox'}")
            print(f"Tiles processed: {processed_tiles}/{len(tiles)}")
            print(f"Total notes: {total_notes}")
            print(f"Power infrastructure notes: {power_notes}")
            print(f"Power note percentage: {(power_notes/total_notes*100):.1f}%" if total_notes > 0 else "0%")
            print(f"Keywords used: {len(keywords)}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Import power infrastructure related OSM Notes for entire countries.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    geo_group = parser.add_argument_group('Geographic Scope')
    geo_group.add_argument('--country', help='Country name to download notes for')
    geo_group.add_argument('--bbox', help='Custom bounding box (min_lon,min_lat,max_lon,max_lat)')
    geo_group.add_argument('--tile-size', type=float, default=0.5,
                          help='Maximum size of each tile in degrees')
    
    filter_group = parser.add_argument_group('Power Infrastructure Filtering')
    filter_group.add_argument('--keywords-file', help='File containing additional keywords')
    filter_group.add_argument('--list-keywords', action='store_true',
                             help='List built-in power infrastructure keywords and exit')
    
    api_group = parser.add_argument_group('API Parameters')
    api_group.add_argument('--limit', type=int, default=10000,
                          help='Maximum number of notes to retrieve per tile')
    api_group.add_argument('--closed', type=int, default=7,
                          help='Number of days of closed notes to include')
    api_group.add_argument('--rate-limit', type=float, default=1.0,
                          help='Delay in seconds between API requests')
    api_group.add_argument('--user-agent', default='OSM Power Infrastructure Notes Importer/1.0',
                          help='User agent string for API requests')
    
    options_group = parser.add_argument_group('Options')
    options_group.add_argument('--create-tables', action='store_true',
                              help='Create database tables if they do not exist')
    options_group.add_argument('--stop-on-error', action='store_true',
                              help='Stop import process on first error')
    options_group.add_argument('--max-tiles', type=int,
                              help='Maximum number of tiles to process (for testing)')
    options_group.add_argument('-q', '--quiet', action='store_true',
                              help='Suppress progress output')
    
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_arguments()
    
    if args.list_keywords:
        print("Built-in power infrastructure keywords:")
        for keyword in sorted(POWER_KEYWORDS):
            print(f"  {keyword}")
        print(f"\nTotal: {len(POWER_KEYWORDS)} keywords")
        return
    
    if not args.country and not args.bbox:
        print("Error: Must specify either --country or --bbox", file=sys.stderr)
        print("Use --help for more information", file=sys.stderr)
        sys.exit(1)
    
    try:
        import_country_power_notes(args)
    except KeyboardInterrupt:
        print("\nImport interrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during import: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()