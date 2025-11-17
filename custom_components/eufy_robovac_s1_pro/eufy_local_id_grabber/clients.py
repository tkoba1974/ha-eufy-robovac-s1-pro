import hmac
import json
import math
import random
import string
import time
import uuid
from hashlib import md5, sha256
from urllib.parse import urljoin

import requests

from .constants import (
    EUFY_BASE_URL,
    EUFY_CLIENT_ID,
    EUFY_CLIENT_SECRET,
    EUFY_HMAC_KEY,
    LANGUAGE,
    PLATFORM,
    TIMEZONE,
    TUYA_CLIENT_ID,
    TUYA_INITIAL_BASE_URL,
)
from .crypto import TUYA_PASSWORD_INNER_CIPHER, shuffled_md5, unpadded_rsa

DEFAULT_EUFY_HEADERS = {
    "User-Agent": "EufyHome-Android-2.4.0",
    "timezone": TIMEZONE,
    "category": "Home",
    # the original app has a bug/oversight where sends these as blank on the initial request
    # we replicate that to avoid detection as much as possible
    # when we login these will be overridden by the real values
    "token": "",
    "uid": "",
    "openudid": PLATFORM,
    "clientType": "2",
    "language": LANGUAGE,
    "country": "US",
    "Accept-Encoding": "gzip",
}


DEFAULT_TUYA_HEADERS = {"User-Agent": "TY-UA=APP/Android/2.4.0/SDK/null"}

# from decompiling the Android app
SIGNATURE_RELEVANT_PARAMETERS = {
    "a",
    "v",
    "lat",
    "lon",
    "lang",
    "deviceId",
    "appVersion",
    "ttid",
    "isH5",
    "h5Token",
    "os",
    "clientId",
    "postData",
    "time",
    "requestId",
    "et",
    "n4h5",
    "sid",
    "sp",
}

DEFAULT_TUYA_QUERY_PARAMS = {
    "appVersion": "2.4.0",
    "deviceId": "",
    "platform": PLATFORM,
    "clientId": TUYA_CLIENT_ID,
    "lang": LANGUAGE,
    "osSystem": "12",
    "os": "Android",
    "timeZoneId": TIMEZONE,
    "ttid": "android",
    "et": "0.0.1",
    "sdkVersion": "3.0.8cAnker",
}


class EufyHomeSession:
    base_url = None
    email = None
    password = None

    def __init__(self, email, password):
        self.session = requests.session()
        self.session.headers = DEFAULT_EUFY_HEADERS.copy()
        self.base_url = EUFY_BASE_URL
        self.email = email
        self.password = password

    def url(self, path):
        return urljoin(self.base_url, path)

    def login(self, email, password):
        resp = self.session.post(
            self.url("user/email/login"),
            json={
                "client_Secret": EUFY_CLIENT_SECRET,
                "client_id": EUFY_CLIENT_ID,
                "email": email,
                "password": password,
            },
        )

        resp.raise_for_status()
        data = resp.json()

        access_token = data["access_token"]
        user_id = data["user_info"]["id"]
        new_base_url = data["user_info"]["request_host"]

        self.session.headers["uid"] = user_id
        self.session.headers["token"] = access_token
        self.base_url = new_base_url

    def _request(self, *args, **kwargs):
        if not self.session.headers["token"] or not self.session.headers["uid"]:
            self.login(self.email, self.password)

        resp = self.session.request(*args, **kwargs)
        resp.raise_for_status()

        return resp.json()

    def get_devices(self):
        # Not actually needed; Eufy uses a single Tuya account per user so we can lookup the devices there
        # however you may still want to consult this for human-readable product names
        # as Tuya only returns generic product IDs and presumably has no knowledge of user-facing names
        return self._request("GET", self.url("device/v2")).get("devices", [])

    def get_user_info(self):
        return self._request("GET", self.url("user/info"))["user_info"]


class TuyaAPISession:
    username = None
    country_code = None
    session_id = None

    def __init__(self, username, country_code):
        self.session = requests.session()
        self.session.headers = DEFAULT_TUYA_HEADERS.copy()
        self.default_query_params = DEFAULT_TUYA_QUERY_PARAMS.copy()
        self.default_query_params["deviceId"] = self.device_id = self.generate_new_device_id()

        self.username = username
        self.country_code = country_code

        self.base_url = TUYA_INITIAL_BASE_URL

    def url(self, path):
        return urljoin(self.base_url, path)

    @staticmethod
    def generate_new_device_id():
        """
        In the Eufy Android app this is generated as follows:

        ```
        private static String getRemoteDeviceID(Context paramContext) {
            StringBuilder stringBuilder1 = new StringBuilder();
            stringBuilder1.append(Build.BRAND);
            stringBuilder1.append(Build.MODEL);
            String str1 = MD5Util.md5AsBase64(stringBuilder1.toString());
            StringBuilder stringBuilder2 = new StringBuilder();
            stringBuilder2.append(getAndroidId(paramContext));
            stringBuilder2.append(getSerialNum());
            String str2 = MD5Util.md5AsBase64(stringBuilder2.toString());
            StringBuilder stringBuilder3 = new StringBuilder();
            stringBuilder3.append(getImei(paramContext));
            stringBuilder3.append(getImsi(paramContext));
            String str3 = MD5Util.md5AsBase64(stringBuilder3.toString());
            StringBuilder stringBuilder4 = new StringBuilder();
            stringBuilder4.append(str1.substring(4, 16));
            stringBuilder4.append(str2.substring(8, 24));
            stringBuilder4.append(str3.substring(16));
            return stringBuilder4.toString();
          }
        ```

        In short, we should be able to get away with a random 44-char string,
        though the first 12 characters of the resulting value are sourced from "str1" which
        is a hash of the device's brand & model, and as such could be predictable and may need to be faked
        to a popular device's make/model to make detection & blocking harder (as they'd block legitimate devices too).
        """
        expected_length = 44
        base64_characters = string.ascii_letters + string.digits  # TODO: is this correct?

        device_id_dependent_part = "8534c8ec0ed0"  # from Google Pixel in an Android Virtual Device
        return device_id_dependent_part + "".join(
            random.choice(base64_characters) for _ in range(expected_length - len(device_id_dependent_part))
        )

    @staticmethod
    def encode_post_data(data: dict) -> str:
        # Note: the rest of the code relies on empty dicts being encoded as a blank string as opposed to "{}"
        return json.dumps(data, separators=(",", ":")) if data else ""

    @staticmethod
    def get_signature(query_params: dict, encoded_post_data: str):
        """
        Tuya's proprietary request signature algorithm.

        This relies on HMAC'ing specific query parameters (defined in SIGNATURE_RELEVANT_PARAMETERS)
        as well as the data, if any. If data is present, it is included in the parameters to be hashed
        as "postData" and then MD5 & the resulting hash shuffled, where as query parameter values
        are passed through as-is.

        The HMAC key is derived from the app secret value "TUYA_SMART_SECRET" in the Android app's metadata
        as well as a value obfuscated in an innocent-looking bitmap image in the app's assets. There is also
        provision for the key to include the app's signing certificate, but in the Eufy build it just defaults to "A".
        """
        query_params = query_params.copy()

        if encoded_post_data:
            query_params["postData"] = encoded_post_data

        sorted_pairs = sorted(query_params.items())
        filtered_pairs = filter(lambda p: p[0] and p[0] in SIGNATURE_RELEVANT_PARAMETERS, sorted_pairs)
        mapped_pairs = map(
            # postData is pre-emptively hashed (for performance reasons?), everything else is included as-is
            lambda p: p[0] + "=" + (shuffled_md5(p[1]) if p[0] == "postData" else p[1]),
            filtered_pairs,
        )

        message = "||".join(mapped_pairs)
        return hmac.HMAC(key=EUFY_HMAC_KEY, msg=message.encode("utf-8"), digestmod=sha256).hexdigest()

    def _request(
        self,
        action: str,
        version="1.0",
        data: dict = None,
        query_params: dict = None,
        _requires_session=True,
    ):
        if not self.session_id and _requires_session:
            self.acquire_session()

        current_time = time.time()
        request_id = uuid.uuid4()

        extra_query_params = {
            "time": str(int(current_time)),
            "requestId": str(request_id),
            "a": action,
            "v": version,
            **(query_params or {}),
        }

        query_params = {**self.default_query_params, **extra_query_params}
        encoded_post_data = self.encode_post_data(data)

        resp = self.session.post(
            self.url("/api.json"),
            params={
                **query_params,
                "sign": self.get_signature(query_params, encoded_post_data),
            },
            # why do they send JSON as a single form-encoded value instead of just putting it directly in the body?
            # they spent more time implementing the stupid request signature system than actually designing a good API
            data={"postData": encoded_post_data} if encoded_post_data else None,
        )

        resp.raise_for_status()
        data = resp.json()

        if "result" not in data:
            raise Exception(f"No 'result' key in the response - the entire response is {data}.")

        return data["result"]

    def request_token(self, username, country_code):
        return self._request(
            action="tuya.m.user.uid.token.create",
            data={"uid": username, "countryCode": country_code},
            _requires_session=False,
        )

    def determine_password(self, username: str):
        new_uid = username
        padded_size = 16 * math.ceil(len(new_uid) / 16)
        password_uid = new_uid.zfill(padded_size)

        encryptor = TUYA_PASSWORD_INNER_CIPHER.encryptor()
        encrypted_uid = encryptor.update(password_uid.encode("utf8"))
        encrypted_uid += encryptor.finalize()

        # from looking into the Android app the password now appears to be MD5-hashed
        return md5(encrypted_uid.hex().upper().encode("utf-8")).hexdigest()

    def request_session(self, username, country_code):
        password = self.determine_password(username)
        token_response = self.request_token(username, country_code)

        encrypted_password = unpadded_rsa(
            key_exponent=int(token_response["exponent"]),
            key_n=int(token_response["publicKey"]),
            plaintext=password.encode("utf-8"),
        )

        data = {
            "uid": username,
            "createGroup": True,
            "ifencrypt": 1,
            "passwd": encrypted_password.hex(),
            "countryCode": country_code,
            "options": '{"group": 1}',
            "token": token_response["token"],
        }

        session_response = self._request(
            action="tuya.m.user.uid.password.login.reg",
            data=data,
            _requires_session=False,
        )

        return session_response

    def acquire_session(self):
        session_response = self.request_session(self.username, self.country_code)
        self.session_id = self.default_query_params["sid"] = session_response["sid"]
        self.base_url = session_response["domain"]["mobileApiUrl"]

    def list_homes(self):
        return self._request(action="tuya.m.location.list", version="2.1")

    def list_devices(self, home_id: str):
        return self._request(
            action="tuya.m.my.group.device.list",
            version="1.0",
            query_params={"gid": home_id},
        )
