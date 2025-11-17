# from Android Eufy App
EUFY_CLIENT_ID = "eufyhome-app"
EUFY_CLIENT_SECRET = "GQCpr9dSp3uQpsOMgJ4xQ"

# from capturing traffic
EUFY_BASE_URL = "https://home-api.eufylife.com/v1/"

# these are presumably obtained from the Android device's status
PLATFORM = "sdk_gphone64_arm64"
LANGUAGE = "en"
TIMEZONE = "Europe/London"


# from Eufy Home Android app
TUYA_CLIENT_ID = "yx5v9uc3ef9wg3v9atje"

# from testing it seems like any region is fine for initial logins
# the login response then contains the proper URL which should be used for subsequent requests
TUYA_INITIAL_BASE_URL = "https://a1.tuyaeu.com"


# Eufy Home "TUYA_SMART_SECRET" Android app metadata value
APPSECRET = "s8x78u7xwymasd9kqa7a73pjhxqsedaj"

# obtained using instructions at https://github.com/nalajcie/tuya-sign-hacking
BMP_SECRET = "cepev5pfnhua4dkqkdpmnrdxx378mpjr"

# turns out this is not used by the Eufy app but this is from the Eufy Home app in case it's useful
# APP_CERT_HASH = "A4:0D:A8:0A:59:D1:70:CA:A9:50:CF:15:C1:8C:45:4D:47:A3:9B:26:98:9D:8B:64:0E:CD:74:5B:A7:1B:F5:DC"

# hmac_key = f'{APP_CERT_HASH}_{BMP_SECRET}_{APPSECRET}'.encode('utf-8')
# turns out this app just uses "A" instead of the app's certificate hash
EUFY_HMAC_KEY = f"A_{BMP_SECRET}_{APPSECRET}".encode()

# from https://github.com/mitchellrj/eufy_robovac/issues/1
TUYA_PASSWORD_KEY = bytearray([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196])
TUYA_PASSWORD_IV = bytearray([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71])
