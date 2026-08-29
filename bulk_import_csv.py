import os
import sys
import csv
import sqlite3
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("BULK_IMPORT")

DB_PATH = os.path.expanduser("~/kingshot-bot/data/kingshot.db")

def parse_csv_file(file_path):
    """Parses and cleans the CSV data handling trailing commas and spaces."""
    players = []
    with open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Split by comma and strip extra whitespaces/trailing commas
            parts = [p.strip() for p in line.split(',') if p.strip()]
            
            # Skip header row
            if len(parts) >= 2:
                name = parts[0]
                fid_str = parts[1]
                
                if name.lower() in ["name", "nickname"] or fid_str.lower() in ["id #", "id", "fid"]:
                    continue
                
                # Ensure fid is numeric
                if fid_str.isdigit():
                    players.append((fid_str, name))
                else:
                    logger.warning(f"Skipping invalid row: {line}")
    return players

def bulk_import_csv(csv_file, server_id, is_starred=0):
    if not os.path.exists(csv_file):
        logger.error(f"CSV file not found at: {csv_file}")
        return

    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at: {DB_PATH}. Make sure the path is correct.")
        return

    players = parse_csv_file(csv_file)
    logger.info(f"Loaded {len(players)} valid player entries from '{csv_file}'.")
    logger.info(f"Target Server (Kingdom) ID: {server_id}")

    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()

        added_count = 0
        skipped_count = 0

        for fid, nickname in players:
            # Check if player already exists
            cursor.execute("SELECT 1 FROM players WHERE fid = ?", (fid,))
            if cursor.fetchone():
                logger.info(f"Skipping {nickname} ({fid}): Already in database.")
                skipped_count += 1
                continue

            # Insert new player
            cursor.execute(
                "INSERT INTO players (fid, nickname, kid, is_starred) VALUES (?, ?, ?, ?)",
                (fid, nickname, server_id, is_starred)
            )
            logger.info(f"Added: {nickname} (ID: {fid}, Server: {server_id})")
            added_count += 1

        conn.commit()
        conn.close()

        logger.info("=" * 45)
        logger.info(f"Import Finished! Added: {added_count} | Skipped: {skipped_count}")
        logger.info("=" * 45)

    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

if __name__ == "__main__":
    # 1. Get CSV file path
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "TRU Database(Members).csv"
    
    # 2. Get Server ID
    if len(sys.argv) > 2:
        kid = int(sys.argv[2])
    else:
        kid_input = input("Enter the Server / Kingdom ID (e.g. 718): ").strip()
        while not kid_input.isdigit():
            kid_input = input("Invalid ID. Enter a numeric Server / Kingdom ID: ").strip()
        kid = int(kid_input)

    bulk_import_csv(csv_path, kid)
