import sys

from .clients import EufyHomeSession, TuyaAPISession

eufy_client = EufyHomeSession(email=sys.argv[1], password=sys.argv[2])
user_info = eufy_client.get_user_info()

tuya_client = TuyaAPISession(username=f'eh-{user_info["id"]}', country_code=user_info["phone_code"])

for home in tuya_client.list_homes():
    print("Home:", home["groupId"])

    for device in tuya_client.list_devices(home["groupId"]):
        print(f"Device: {device['name']}, device ID {device['devId']}, local key {device['localKey']}")
