import os
import sqlite3
import sys
import logging

# Setup basic logging to see exactly what gets deleted
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("BULK_DELETE")

# Use your project's pathing
DB_PATH = os.path.expanduser("~/kingshot-bot/data/kingshot.db")
IDS_FILE = os.path.expanduser("~/kingshot-bot/ids.txt")

def bulk_delete():
    if not os.path.exists(IDS_FILE):
        logger.error(f"ID file not found at {IDS_FILE}. Please create it first.")
        sys.exit(1)

    # Read and parse IDs from file (ignores empty lines and whitespace)
    with open(IDS_FILE, 'r') as f:
        fids = [line.strip() for line in f if line.strip()]

    if not fids:
        logger.warning("No IDs found in ids.txt. Nothing to delete.")
        return

    logger.info(f"Loaded {len(fids)} IDs from ids.txt to process.")

    try:
        # check_same_thread=False is used just like in your main project setup
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()

        # Track deletion count
        deleted_players = 0
        deleted_redemptions = 0

        # Process each ID
        for fid in fids:
            try:
                # 1. Clean up redemptions first to respect foreign keys/database cleanlines
                cursor.execute("DELETE FROM redemptions WHERE fid = ?", (fid,))
                deleted_redemptions += cursor.rowcount

                # 2. Delete the player
                cursor.execute("DELETE FROM players WHERE fid = ?", (fid,))
                
                if cursor.rowcount > 0:
                    logger.info(f"Successfully deleted player: {fid}")
                    deleted_players += 1
                else:
                    logger.warning(f"Player ID {fid} not found in database (skipped).")

            except sqlite3.Error as e:
                logger.error(f"Error processing ID {fid}: {e}")

        # Commit all changes to disk
        conn.commit()
        conn.close()

        logger.info("--- WORK COMPLETED ---")
        logger.info(f"Players deleted: {deleted_players}")
        logger.info(f"Redemption histories cleared: {deleted_redemptions}")

    except sqlite3.Error as e:
        logger.critical(f"Failed to connect to database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    bulk_delete()
