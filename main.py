import sys
import time
import logging
import random
from collections import defaultdict, deque, Counter
from datetime import datetime, timedelta
from API_Manager import KingshotAPI
from Database_Manager import DatabaseManager
import constants

# --- LOGGING SETUP ---
logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-4s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(constants.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
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
                        # Only count actual success as a "Redemption" for stats
                        stats_redemptions[fid] += 1
                    
                    self.db.log_successful_redemption(fid, code, result)
                    consecutive_player_errors = 0 
                
                # CASE B : EXPIRED (Global)
                elif err_code == 40007:
                    logger.warning(f"Code {code} is EXPIRED. Skipping for everyone.")
                    known_expired_codes.add(code)
                
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
                pass # Player finished all codes successfully (or skipped them)

        # 4. FINAL STATS
        logger.info("--- Redemption Cycle Completed ---")
        logger.info(f"Players processed: total - {total_players_start}, skipped (Already Had All): {stats_skipped_full}, skipped (Errors/Dropped):  {stats_skipped_error}")
        
        if failed_players:
            logger.info(f"   -> Failed Players: {', '.join(failed_players)}")

        # Count how many players got X codes
        # We excluding players with 0s if they were counted in "Skipped Full"
        # But if they needed codes and got 0 (due to expiry), they end up here with 0.
        
        redeem_counts = [v for k,v in stats_redemptions.items() if v > 0]
        
        if not redeem_counts:
            logger.info("   No new codes were redeemed for any player.")
        else:
            # Counter({1: 5, 3: 2}) -> 5 players got 1 code, 2 players got 3 codes
            distribution = Counter(redeem_counts)
            for count, num_players in sorted(distribution.items(), reverse=True):
                p_text = "player" if num_players == 1 else "players"
                c_text = "code" if count == 1 else "codes"
                logger.info(f"   • {num_players} {p_text} redeemed {count} {c_text}")
                
        logger.info("="*40 + "\n")

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
 

# For real use:
# if __name__ == "__main__":
#     bot = KingshotBot()
#     bot.run_daily_loop()

# For testing: 
if __name__ == "__main__":
    bot = KingshotBot()
    print("\n=== STEP 0: VERIFYING DB CONTENT ===")
    bot.db.show_full_table()
    print("\n=== STEP 1: SEEDING DATABASE ===")
    test_ids = [
        "111111112",
        "12345678",
        "200215960",
        "151247588",
        "152443639",
        "177950447",
        "207592349",
        "8767319",
        "12345678",
        "105852213"
        "226431996",
    ]

    added_count = 0
    skipped_count = 0
    
    for fid_str in test_ids:
        fid = int(fid_str)
        if bot.db.player_exists(fid):
            print(f"Skipped check: {fid} (Already in Database)")
            continue
        player_data = bot.api.get_player_info(fid)
        if player_data:
            bot.db._save_player_to_db(player_data)
            print(f"Saved: {player_data['nickname']} (Lv.{player_data['stove_lv']})")
            added_count += 1
        else:
            skipped_count += 1
        time.sleep(1.0) 
    print("\n" + "="*30)
    print(f"   Players Added/Verified: {added_count}")
    print(f"   IDs Skipped (Invalid):  {skipped_count}")
    print("="*30 + "\n")

    print("\n=== STEP 2: VERIFYING DB CONTENT ===")
    bot.db.show_full_table()

    print("\n=== STEP 3: STARTING AUTOMATION ===")
    print("Bot is now running. Press Ctrl+C to stop.")

    bot.run_once()