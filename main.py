import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import random
from collections import defaultdict, deque, Counter
from datetime import datetime, timedelta
from API_Manager import KingshotAPI
from Database_Manager import DatabaseManager
import constants

# --- LOGGING SETUP ---
class DiscordNameFilter(logging.Filter):
    def filter(self, record):
        if record.name.startswith("discord"):
            record.name = "BOT"
        return True
    
logging.Formatter.converter = time.gmtime

file_handler = RotatingFileHandler(
    constants.LOG_FILE, 
    maxBytes= 5*1024*1024, # 5 MB per file
    backupCount=3,        # Keep 3 old log files (15MB total max)
    encoding='utf-8'
)

stream_handler = logging.StreamHandler(sys.stdout)

discord_filter = DiscordNameFilter()
file_handler.addFilter(discord_filter)
stream_handler.addFilter(discord_filter)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-4s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[file_handler, stream_handler]
)

logger = logging.getLogger("MAIN")

# --- MAIN BOT CLASS ---
class KingshotBot:
    def __init__(self):
        self.api = KingshotAPI()
        self.db = DatabaseManager()
        self.error_threshold = 5   # Pause after 5 consecutive unknown errors
        self.pause_duration = 180  # Pause for 3 minutes (180s)
        self.request_delay = 5     # Wait 5s between requests

    def check_for_new_codes(self):
        """Checks for new codes and marks them as announced in the database."""
        active_codes = self.api.get_active_codes()
        new_codes = []
        for code in active_codes:
            if not self.db.is_code_announced(code):
                self.db.mark_code_announced(code)
                new_codes.append(code)
        return new_codes

    def redeem_for_player(self, fid):
        logger.info(f"--- Starting redemption for ID: {fid} ---")
        
        # 1. Fetch all active codes
        active_codes = self.api.get_active_codes()
        if not active_codes:

            return {"status": "error", "msg": "No active codes found at the moment."}
        # 2. Identify Player and Handle Login
        player_record = self.db.get_player(fid)
        if not player_record:
            return {"status": "error", "msg": f"Player with ID {fid} not found in database. Please add them first using /add."}

        nickname = player_record['nickname']
        kid = player_record['kid']
        results = []
        redeemed_count = 0
        
        for code in active_codes:
            if self.db.is_code_redeemed(fid, code):
                results.append(f"{code}: Already redeemed")
                continue

            time.sleep(self.request_delay)
            res = self.api.redeem_code(fid, kid, code)
            
            status_code = res.get('code')
            err_code = res.get('err_code')
            msg = res.get('msg', 'Unknown Error')

            if status_code == 0 or err_code in [20000, 40008, 40011]:
                self.db.log_successful_redemption(fid, code, res)
                results.append(f"{code}: Success")
                redeemed_count += 1
            else:
                results.append(f"{code}: Failed - {msg}")
                logger.warning(f"Targeted redeem failed for {fid} on {code}: {msg}")

        logger.info(f"--- Finished redemption for {nickname} ---")
        return {
            "status": "success",
            "nickname": nickname,
            "fid": fid,
            "total_active": len(active_codes),
            "redeemed_new": redeemed_count,
            "details": results
        }

    def run_redemption_cycle(self):
        logger.info("--- Starting Redemption Cycle...")

        active_codes = self.api.get_active_codes()
        if not active_codes:
            logger.info("No active codes found. Ending cycle.")
            return

        # Check for newly discovered codes right before redeeming
        new_codes_found = []
        for c in active_codes:
            if not self.db.is_code_announced(c):
                self.db.mark_code_announced(c)
                new_codes_found.append(c)

        # 2. Fetch Players
        players = self.db.show_all_players()
        if not players:
            logger.warning("No players in database. Add players first.")
            return

        # 3. Create Queue
        queue = deque([(p, 0) for p in players])

        # Statistic Trackers 
        stats_redemptions = defaultdict(int)
        stats_skipped_full = 0   # Players who needed 0 codes
        stats_already_claimed = 0 # Players attempted, but all codes were already claimed in-game
        stats_skipped_error = 0  # Players dropped due to max retries
        failed_players = []      # List of names who failed

        # Operational Trackers
        consecutive_player_errors = 0
        known_expired_codes = set()
        
        total_players_start = len(players)

        logger.info(f"Loaded {total_players_start} players and {len(active_codes)} codes.")

        while queue:
            player, retries = queue.popleft()
            fid = player['fid']
            nickname = player['nickname']
            kid = player['kid']

            codes_to_try = []

            for code in active_codes:
                # CASE A: Skip if we know it's expired for everyone
                if code in known_expired_codes:
                    continue
                # CASE B: Skip if THIS player already has it in DB
                if self.db.is_code_redeemed(fid, code):
                    continue
                
                codes_to_try.append(code)

            # If no codes are needed, SKIP entirely.
            if not codes_to_try:
                if stats_redemptions[fid] == 0:
                    stats_skipped_full += 1
                    logger.info(f"Skipping {nickname}: All codes already redeemed.")
                continue

            player_had_error = False
            
            for code in codes_to_try:
                result = self.api.redeem_code(fid, kid, code)
                err_code = result.get('err_code')
                status_code = result.get('code')
                
                # CASE A: SUCCESS / ALREADY CLAIMED / MUTUALLY EXCLUSIVE
                if status_code == 0 or err_code in [20000, 40008, 40011]:
                    if status_code == 0 or err_code == 20000:
                        stats_redemptions[fid] += 1
                    
                    self.db.log_successful_redemption(fid, code, result)
                    consecutive_player_errors = 0 
                
                # CASE B : EXPIRED (Global) or Claim limit reached
                elif err_code in [40007, 40005]:
                    logger.warning(f"Code {code} is EXPIRED. Skipping for everyone.")
                    known_expired_codes.add(code)

                # CASE C : Player doesn't meet requirements (Level, etc)
                elif err_code in [40006, 40017]:
                    logger.info(f"Player {nickname} does not meet requirements for Code {code}. Skipping.")
                
                # CASE D: ERROR (Network, Unknown, Not Login)
                else:
                    msg = result.get('msg', 'Unknown')
                    logger.warning(f"Failed {nickname} on {code}: {msg} (Err: {err_code})")
                    player_had_error = True
                    break
                
                time.sleep(self.request_delay)

            # 3. QUEUE MANAGEMENT
            if player_had_error:
                consecutive_player_errors += 1
                if retries < 2:
                    logger.info(f"Re-queueing {nickname} due to error.")
                    queue.append((player, retries + 1))
                    self._check_pause(consecutive_player_errors)
                else:
                    logger.error(f"Dropping {nickname} after 3 failed attempts.")
                    stats_skipped_error += 1
                    failed_players.append(nickname)
            else:
                # If processed without error, but 0 NEW codes were successfully redeemed for rewards
                if stats_redemptions[fid] == 0:
                    stats_already_claimed += 1

    # 4. FINAL STATS
        logger.info("--- Redemption Cycle Completed ---")
        
        redeem_counts = [v for k, v in stats_redemptions.items() if v > 0]
        distribution = Counter(redeem_counts) if redeem_counts else {}
        
        return {
            "total_players": total_players_start,
            "skipped_full": stats_skipped_full,
            "skipped_error": stats_skipped_error,
            "already_claimed": stats_already_claimed,
            "failed_players": failed_players,
            "distribution": distribution,
            "new_codes": new_codes_found
        }

    def _check_pause(self, error_count):
        if error_count >= self.error_threshold:
            logger.warning(f"SERIOUS ERROR: {error_count} Players failed in a row. Pausing for {self.pause_duration}s...")
            time.sleep(self.pause_duration)

    def run_once(self):
        try:
            self.run_redemption_cycle()
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            sys.exit()

if __name__ == "__main__":
    bot = KingshotBot()