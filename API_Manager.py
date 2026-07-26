import logging
import requests
import time
import hashlib
import constants

class KingshotAPI:
    def __init__(self):
        self.logger = logging.getLogger("API")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://ks-giftcode.centurygame.com",
            "Referer": "https://ks-giftcode.centurygame.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self.request_delay = 5

    def _generate_sign(self, params):
        sorted_keys = sorted(params.keys())
        raw_string = "&".join([f"{k}={params[k]}" for k in sorted_keys])
        raw_string += constants.SALT
        return hashlib.md5(raw_string.encode("utf-8")).hexdigest()

    def redeem_code(self, fid, kid, cdk):
        time.sleep(self.request_delay)
        current_time = str(int(time.time()))
        params = {
            "cdk": str(cdk),
            "fid": str(fid),
            "kid": str(kid),
            "time": current_time,
        }
        payload = params.copy()
        payload['sign'] = self._generate_sign(params)

        try:
            response = self.session.post(constants.REDEEM_URL, data=payload, timeout=10)
            result = response.json()

            if result.get("code") == 0 or result.get("err_code") == 20000:
                self.logger.info(f"Redemption SUCCESS for {fid} - Code: {cdk}")
            elif result.get("err_code") == 40008:
                self.logger.info(f"Redemption SKIPPED for {fid} - Code: {cdk} (Already Redeemed)")
            elif result.get("err_code") == 40011:
                self.logger.info(f"Redemption SKIPPED for {fid} - Code: {cdk} (Equivalent was already redeemed)") 
            else:
                self.logger.warning(f"Redemption FAILED for {fid} - Code: {cdk} | Msg: {result.get('msg')}")

            return result
        except Exception as e:
            self.logger.error(f"Redeem error for {fid}/{cdk}: {e}")
            return {"error": str(e)}

    def get_active_codes(self):
        time.sleep(self.request_delay)
        self.logger.info("Fetching active gift codes...")
        try:
            response = requests.get(constants.ACTIVE_CODES_URL, timeout=10)
            data = response.json()
            if data.get("status") == "success":
                codes = data['data']['giftCodes']
                code_list = [item['code'] for item in codes]
                self.logger.info(f"Found {len(code_list)} active codes: {', '.join(code_list)}")
                return code_list
            else:
                self.logger.warning("Failed to fetch codes: API status was not 'success'")
                return []
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error fetching codes: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching codes: {e}")
            return []