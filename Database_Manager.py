import logging
import sqlite3
import constants

class DatabaseManager:
    def __init__(self):
        self.logger = logging.getLogger("DB")
        self.conn = sqlite3.connect(constants.DB_NAME, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row 
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    fid INTEGER PRIMARY KEY,
                    nickname TEXT,
                    kid INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fid INTEGER,
                    code TEXT,
                    redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(fid, code),
                    FOREIGN KEY (fid) REFERENCES players (fid)
                )
            ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    target_channel_id INTEGER
                )
            ''')
            self.conn.commit()
            self.logger.info("Database tables initialized successfully.")
        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}")

    def _set_guild_channel(self, guild_id, channel_id):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO guild_settings (guild_id, target_channel_id) VALUES (?, ?)",
                (guild_id, channel_id)
            )
            self.conn.commit()
        except Exception as e:
            self.logger.error(f"Error setting guild channel: {e}")

    def _delete_guild_channel(self, guild_id):
        try:
            self.cursor.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Error deleting guild channel: {e}")
            return False

    def _save_player_to_db(self, data):
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO players (fid, nickname, kid) VALUES (?, ?, ?)", 
                (data['fid'], data['nickname'], data['kid'])
            )
            self.conn.commit()

            if self.cursor.rowcount > 0:
                self.logger.info(f"New player saved: {data['nickname']}")
            else:
                self.logger.info(f"Player already exists: {data['nickname']} (Skipped)")

        except Exception as e:
            self.logger.error(f"Database error saving player: {e}")

    def _delete_player(self, fid):
        try:
            self.cursor.execute('DELETE FROM players WHERE fid = ?', (fid,))
            self.conn.commit()
            if self.cursor.rowcount > 0:
                self.logger.info(f"Deleted player with ID {fid}.")
                return True
            else:
                self.logger.warning(f"No player found with ID {fid} to delete.")
                return False
        except Exception as e:
            self.logger.error(f"Database error deleting player: {e}")
            return False

    def _update_player_info(self, fid, new_nickname, new_kid):
        try:
            self.cursor.execute(
                "UPDATE players SET nickname = ?, kid = ? WHERE fid = ?", 
                (new_nickname, new_kid, fid)
            )
            self.conn.commit()
            if self.cursor.rowcount > 0:
                self.logger.info(f"Updated player info for ID {fid}")
        except Exception as e:
            self.logger.error(f"Database error updating player info for {fid}: {e}")

    def get_all_registrations(self):
        try:
            self.cursor.execute("SELECT guild_id, target_channel_id FROM guild_settings")
            return self.cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Error fetching all registrations: {e}")
            return []

    def get_all_target_channels(self):
        try:
            self.cursor.execute("SELECT target_channel_id FROM guild_settings")
            return [row['target_channel_id'] for row in self.cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Error fetching target channels: {e}")
            return []

    def is_guild_registered(self, guild_id):
        self.cursor.execute("SELECT 1 FROM guild_settings WHERE guild_id = ?", (guild_id,))
        return self.cursor.fetchone() is not None

    def show_all_players(self):
        self.cursor.execute('SELECT fid, nickname, kid FROM players')
        return self.cursor.fetchall()
    
    def get_all_fids(self):
        self.cursor.execute('SELECT fid FROM players')
        return [row['fid'] for row in self.cursor.fetchall()]

    def check_codes_redeemed(self, fid):
        self.cursor.execute('SELECT code FROM redemptions WHERE fid = ?', (fid,))
        return [row['code'] for row in self.cursor.fetchall()]

    def log_successful_redemption(self, fid, code_str, response):
        is_success = ( 
            (response.get('code') == 0) or 
            (response.get('err_code') == 20000) or 
            (response.get('err_code') == 40008) or
            (response.get('err_code') == 40011)
        )
        
        if is_success:
            try:
                self.cursor.execute(
                    "INSERT OR IGNORE INTO redemptions (fid, code) VALUES (?, ?)", 
                    (fid, code_str)
                )
                self.conn.commit()
                if self.cursor.rowcount > 0:
                    if response.get('err_code') == 40011:
                         self.logger.info(f"Logged code {code_str} for {fid} (Equivalent of this code was already redeemed).")
                    else:
                         self.logger.info(f"Logged redeemed code {code_str} for {fid}.")
            except Exception as e:
                self.logger.error(f"Database error logging code: {e}")

    def show_full_table(self):
        query = '''
            SELECT p.fid, p.nickname, p.added_date, GROUP_CONCAT(r.code, ', ') as codes
            FROM players p
            LEFT JOIN redemptions r ON p.fid = r.fid
            GROUP BY p.fid
        '''
        self.cursor.execute(query)
        players = self.cursor.fetchall()

        self.logger.info(f"{'Player ID':<15} | {'Nickname':<15} | {'Codes'}")
        self.logger.info("-" * 60)
        for p in players:
            codes = p['codes'] if p['codes'] else "None"
            self.logger.info(f"{p['fid']:<15} | {p['nickname']:<15} | {codes}")

    def player_exists(self, fid):
        self.cursor.execute('SELECT 1 FROM players WHERE fid = ?', (fid,))
        return self.cursor.fetchone() is not None
    
    def get_player(self, fid):
        self.cursor.execute('SELECT fid, nickname, kid FROM players WHERE fid = ?', (fid,))
        return self.cursor.fetchone()

    def get_player_count(self):
        self.cursor.execute('SELECT COUNT(*) as count FROM players')
        return self.cursor.fetchone()['count']
    
    def get_kingdom_count(self):
        self.cursor.execute('SELECT COUNT(DISTINCT kid) as count FROM players')
        return self.cursor.fetchone()['count']

    def is_code_redeemed(self, fid, code):
        self.cursor.execute('SELECT 1 FROM redemptions WHERE fid = ? AND code = ?', (fid, code))
        return self.cursor.fetchone() is not None

    def get_servers_stats(self):
        self.cursor.execute("SELECT kid, COUNT(fid) as player_count FROM players GROUP BY kid ORDER BY player_count DESC")
        return self.cursor.fetchall()

    def get_players_by_kid(self, kid):
        self.cursor.execute("SELECT fid, nickname, FROM players WHERE kid = ?", (kid,))
        return self.cursor.fetchall()

    def get_redeemed_codes(self):
        self.cursor.execute('SELECT DISTINCT code FROM redemptions')
        return [row['code'] for row in self.cursor.fetchall()]

    def get_latest_redemption_info(self):
        query = '''
            SELECT code, redeemed_at 
            FROM redemptions 
            WHERE redeemed_at > datetime('now', '-1 day')
            ORDER BY redeemed_at DESC
        '''
        try:
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            
            if not rows:
                return None
                
            latest_timestamp = rows[0]['redeemed_at']
            
            unique_codes = []
            for row in rows:
                if row['code'] not in unique_codes:
                    unique_codes.append(row['code'])
            
            return {
                "timestamp": latest_timestamp,
                "codes": unique_codes
            }
        except Exception as e:
            self.logger.error(f"Error fetching latest session info: {e}")
            return None

    def close(self):
        self.conn.close()
