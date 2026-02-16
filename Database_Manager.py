import sqlite3

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self.conn.row_factory = sqlite3.Row 
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # self.cursor.execute("DROP TABLE IF EXISTS players")
        # self.cursor.execute("DROP TABLE IF EXISTS redemptions")
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                fid INTEGER PRIMARY KEY,
                nickname TEXT,
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
        self.conn.commit()

    def show_all_players(self):
        self.cursor.execute('SELECT fid, nickname FROM players')
        return self.cursor.fetchall()
    
    def get_all_fids(self):
        self.cursor.execute('SELECT fid FROM players')
        return [row['fid'] for row in self.cursor.fetchall()]

    def check_codes_redeemed(self, fid):
        self.cursor.execute('SELECT code FROM redemptions WHERE fid = ?', (fid,))
        return [row['code'] for row in self.cursor.fetchall()]

    def log_successful_redemption(self, fid, code_str, response):
        """Logs a code using the new relational table."""
        is_success = ( 
            (response.get('code') == 0) or 
            (response.get('err_code') == 20000) or 
            (response.get('err_code') == 40008) 
        )
        
        if is_success:
            try:
                self.cursor.execute(
                    "INSERT OR IGNORE INTO redemptions (fid, code) VALUES (?, ?)", 
                    (fid, code_str)
                )
                self.conn.commit()
                if self.cursor.rowcount > 0:
                    print(f"Logged code {code_str} for {fid}.")
            except Exception as e:
                print(f"Database error logging code: {e}")

    def show_full_table(self):
        """Displays combined info using a JOIN."""
        query = '''
            SELECT p.fid, p.nickname, p.added_date, GROUP_CONCAT(r.code, ', ') as codes
            FROM players p
            LEFT JOIN redemptions r ON p.fid = r.fid
            GROUP BY p.fid
        '''
        self.cursor.execute(query)
        players = self.cursor.fetchall()

        print(f"{'Player ID':<15} | {'Nickname':<15} | {'Codes'}")
        print("-" * 60)
        for p in players:
            codes = p['codes'] if p['codes'] else "None"
            print(f"{p['fid']:<15} | {p['nickname']:<15} | {codes}")

    def _save_player_to_db(self, data):
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO players (fid, nickname) VALUES (?, ?)", 
                (data['fid'], data['nickname'])
            )
            self.conn.commit()
        except Exception as e:
            print(f"Database error: {e}")

    def close(self):
        """Safely closes the database connection."""
        self.conn.close()


