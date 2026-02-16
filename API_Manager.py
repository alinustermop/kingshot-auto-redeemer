import requests
import time
import hashlib

class KingshotAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://ks-giftcode.centurygame.com",
            "Referer": "https://ks-giftcode.centurygame.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _generate_sign(self, params):
        sorted_keys = sorted(params.keys())
        raw_string = "&".join([f"{k}={params[k]}" for k in sorted_keys])
        raw_string += SALT
        return hashlib.md5(raw_string.encode("utf-8")).hexdigest()

    def get_player_info(self, fid):
        current_time = str(int(time.time() * 1000))
        params = {
            "fid": fid,
            "time": current_time,
        }
        payload = params.copy()
        payload['sign'] = self._generate_sign(params)

        try:
            response = self.session.post(PLAYER_URL, data=payload, timeout=10)
            response.raise_for_status() 

            data = response.json()
            if data.get("code") == 0:
                return data['data']
            return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Network Error looking up {fid}: {e}")
            return None
        except ValueError:
            print(f"❌ Invalid JSON response for {fid}")
            return None

    def redeem_code(self, fid, cdk):
        current_time = str(int(time.time() * 1000))
        params = {
            "captcha_code": "",
            "cdk": cdk,
            "fid": fid,
            "time": current_time,
        }
        payload = params.copy()
        payload['sign'] = self._generate_sign(params)

        try:
            response = self.session.post(REDEEM_URL, data=payload, timeout=10)
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def get_active_codes(self):
        print("Fetching active gift codes...")
        try:
            response = requests.get(ACTIVE_CODES_URL, timeout=10)
            data = response.json()
            if data.get("status") == "success":
                codes = data['data']['giftCodes']
                code_list = [item['code'] for item in codes]
                print(f"✅ Found {len(code_list)} active codes: {', '.join(code_list)}")
                return code_list
            else:
                print("❌ Failed to fetch codes: API status not success")
                return []
        except Exception as e:
            print(f"❌ Error fetching codes: {e}")
            return []