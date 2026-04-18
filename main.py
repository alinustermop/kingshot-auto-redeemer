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
        self.request_delay = 5     # Wait 5s between requests to be safe

    def redeem_for_player(self, fid):
        logger.info(f"--- Starting redemption for ID: {fid} ---")
        
        # 1. Fetch all active codes
        active_codes = self.api.get_active_codes()
        if not active_codes:
            return {"status": "error", "msg": "No active codes found at the moment."}
        
        # 2. Identify Player and Handle Login
        player_record = self.db.get_player(fid)
        needs_db_save = False
        
        if not player_record:
            player_data = self.api.get_player_info(fid)
            if not player_data:
                return {"status": "error", "msg": f"Could not find a player with ID {fid}."}
            nickname = player_data['nickname']
            needs_db_save = True
        else:
            nickname = player_record['nickname']
            try:
                kid = player_record['kid']
            except (IndexError, KeyError):
                kid = None
            player_data = self.api.get_player_info(fid)
            if not player_data:
                return {"status": "error", "msg": f"Login failed for {nickname} ({fid})."}
            
            if player_data['nickname'] != nickname or player_data['kid'] != kid:
                self.db._update_player_info(fid, player_data['nickname'], player_data['kid'])
                nickname = player_data['nickname']

        if needs_db_save:
            self.db._save_player_to_db(player_data)

        # 3. Process every active code
        results = []
        redeemed_count = 0
        
        for code in active_codes:
            if self.db.is_code_redeemed(fid, code):
                results.append(f"{code}: Already redeemed")
                continue

            time.sleep(self.request_delay)
            res = self.api.redeem_code(fid, code)
            
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

        # 1. Fetch Active Codes
        active_codes = self.api.get_active_codes()
        if not active_codes:
            logger.info("No active codes found. Ending cycle.")
            return

        # 2. Fetch Players
        players = self.db.show_all_players()
        if not players:
            logger.warning("No players in database. Add players first.")
            return

        # 3. Create Queue
        queue = deque([(p, 0) for p in players])
        
        # Statistic Trackers 
        stats_redemptions = defaultdict(int) # {fid: count_of_new_codes}
        stats_skipped_full = 0   # Players who needed 0 codes
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

            codes_to_try = []

            for code in active_codes:
                # CASE A: Skip if we know it's expired for everyone
                if code in known_expired_codes:
                    continue
                # CASE B: Skip if THIS player already has it in DB
                if self.db.is_code_redeemed(fid, code):
                    continue
                
                codes_to_try.append(code)

            # If no codes are needed, SKIP LOGIN entirely.
            if not codes_to_try:
                if stats_redemptions[fid] == 0:
                    stats_skipped_full += 1
                    logger.info(f"Skipping {nickname}: All codes already redeemed.")
                continue

            # 1. LOGIN (Get Player Info)
            profile = self.api.get_player_info(fid)
            
            if not profile:
                # Login failed (Network or Bad ID)
                consecutive_player_errors += 1

                if retries < 2: # Max 3 attempts (0, 1, 2)
                    logger.warning(f"Login failed for {nickname}. Re-queueing (Attempt {retries+1}/3).")
                    queue.append((player, retries + 1))
                    self._check_pause(consecutive_player_errors)
                else:
                    logger.error(f"Dropping {nickname} after 3 failed login attempts.")
                    stats_skipped_error += 1
                    failed_players.append(nickname)
                
                continue
            
            if profile['nickname'] != player['nickname'] or profile['kid'] != player['kid']:
                self.db._update_player_info(fid, profile['nickname'], profile['kid'])

            # Sleep after login
            time.sleep(self.request_delay)

            # 2. REDEEM CODES
            player_had_error = False
            
            for code in codes_to_try:

                # Call API
                result = self.api.redeem_code(fid, code)
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
                
                # CASE C: ERROR (Network, Unknown, Not Login)
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
                pass

    # 4. FINAL STATS
        logger.info("--- Redemption Cycle Completed ---")
        logger.info(f"Players processed: total - {total_players_start}, skipped (Already Had All): {stats_skipped_full}, skipped (Errors/Dropped):  {stats_skipped_error}")
        
        if failed_players:
            logger.info(f"   -> Failed Players: {', '.join(failed_players)}")

        redeem_counts = [v for k,v in stats_redemptions.items() if v > 0]
        distribution = Counter(redeem_counts) if redeem_counts else {}
        
        if not redeem_counts:
            logger.info("   No new codes were redeemed for any player.")
        else:
            for count, num_players in sorted(distribution.items(), reverse=True):
                p_text = "player" if num_players == 1 else "players"
                c_text = "code" if count == 1 else "codes"
                logger.info(f"   • {num_players} {p_text} redeemed {count} {c_text}")
                
        logger.info("="*40 + "\n")

        return {
            "total_players": total_players_start,
            "skipped_full": stats_skipped_full,
            "skipped_error": stats_skipped_error,
            "failed_players": failed_players,
            "distribution": distribution
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

    def run_daily_loop(self):
        logger.info("Bot started in DAILY SCHEDULE mode")
        
        while True:
            try:
                self.run_redemption_cycle()

                # Calculate Sleep (24h +/- 60 mins jitter)
                jitter = random.randint(-3600, 3600)
                sleep_seconds = (24 * 3600) + jitter
                
                next_run = datetime.now() + timedelta(seconds=sleep_seconds)
                logger.info(f"Sleeping until {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                
                time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                logger.info("Bot stopped by user.")
                sys.exit()

            except Exception as e:
                logger.error(f"Unexpected crash in main loop: {e}")
                time.sleep(60)
 

# For testing: 
if __name__ == "__main__":
    bot = KingshotBot()