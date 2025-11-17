"""Discovery module for Tuya devices.

Stolen from the "localtuya" project at:

https://github.com/rospogrigio/localtuya/blob/master/custom_components/localtuya/discovery.py

Which it itself, "entirely based on tuya-convert.py from tuya-convert":

https://github.com/ct-Open-Source/tuya-convert/blob/master/scripts/tuya-discovery.py
"""
import asyncio
import json
import logging
from hashlib import md5

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

UDP_KEY = md5(b"yGAdlopoPVldABfn").digest()

DEFAULT_TIMEOUT = 6.0


def decrypt_udp(message):
    """Decrypt encrypted UDP broadcasts."""

    def _unpad(data):
        return data[: -ord(data[len(data) - 1 :])]

    cipher = Cipher(algorithms.AES(UDP_KEY), modes.ECB(), default_backend())
    decryptor = cipher.decryptor()
    return _unpad(decryptor.update(message) + decryptor.finalize()).decode()


class TuyaDiscovery(asyncio.DatagramProtocol):
    """Datagram handler listening for Tuya broadcast messages."""

    def __init__(self, callback=None):
        """Initialize a new BaseDiscovery."""
        self.devices = {}
        self._listeners = []
        self._callback = callback

    async def start(self):
        """Start discovery by listening to broadcasts."""
        loop = asyncio.get_running_loop()
        
        # Use reuse_port parameter directly as in CodeFoodPixels implementation
        listener = loop.create_datagram_endpoint(
            lambda: self, local_addr=("0.0.0.0", 6666), reuse_port=True
        )
        encrypted_listener = loop.create_datagram_endpoint(
            lambda: self, local_addr=("0.0.0.0", 6667), reuse_port=True
        )

        try:
            self._listeners = await asyncio.gather(listener, encrypted_listener)
            _LOGGER.debug("Listening to broadcasts on UDP port 6666 and 6667")
        except Exception as e:
            _LOGGER.exception(
                "Failed to start discovery on ports 6666 and 6667. "
                "This may be due to another integration (like localtuya) using these ports. "
                "Error: %s", e
            )
            # Don't raise, allow integration to continue without discovery
            self._listeners = []

    def close(self, *args, **kwargs):
        """Stop discovery."""
        self._callback = None
        for listener in self._listeners:
            try:
                transport, _ = listener
                transport.close()
            except Exception as e:
                _LOGGER.debug("Error closing listener: %s", e)

    def datagram_received(self, data, addr):
        """Handle received broadcast message."""
        data = data[20:-8]
        try:
            data = decrypt_udp(data)
        except Exception:  # pylint: disable=broad-except
            try:
                data = data.decode()
            except Exception:
                _LOGGER.debug("Could not decode datagram from %s", addr)
                return

        try:
            decoded = json.loads(data)
            self.device_found(decoded)
        except json.JSONDecodeError:
            _LOGGER.debug("Could not parse JSON from %s: %s", addr, data)

    def device_found(self, device):
        """Discover a new device."""
        device_id = device.get("gwId")
        if device_id and device_id not in self.devices:
            self.devices[device_id] = device
            _LOGGER.debug("Discovered device: %s", device)

        if self._callback:
            self._callback(device)


async def discover():
    """Discover and return devices on local network."""
    discovery = TuyaDiscovery()
    try:
        await discovery.start()
        await asyncio.sleep(DEFAULT_TIMEOUT)
    finally:
        discovery.close()
    return discovery.devices
