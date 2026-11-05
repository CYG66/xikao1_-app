"""Local-network discovery for Dashes rover backends.

The discovery protocol contains no credentials. UDP is used as the reliable
fallback for Android clients; a small mDNS responder is included so standard
network tools can also see the rover as a service.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import signal
import threading
import time
from typing import Any


DISCOVERY_PORT = 8765
MDNS_PORT = 5353
MDNS_GROUP = "224.0.0.251"
SERVICE_TYPE = "_dashes-rover._tcp.local"


def _device_identity() -> str:
    configured = os.getenv("XLINE_DEVICE_ID", "").strip()
    return configured or socket.gethostname()


def _local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _labels(name: str) -> bytes:
    result = bytearray()
    for label in name.rstrip(".").split("."):
        encoded = label.encode("utf-8")
        result.append(len(encoded))
        result.extend(encoded)
    result.append(0)
    return bytes(result)


def _record(name: str, record_type: int, data: bytes, ttl: int = 120) -> bytes:
    return _labels(name) + struct.pack("!HHIH", record_type, 1, ttl, len(data)) + data


class RoverDiscoveryService:
    def __init__(self, http_port: int = 8000) -> None:
        self.http_port = http_port
        self.device_id = _device_identity()
        self.hostname = f"dashes-{self.device_id.lower().replace('_', '-')}.local"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def payload(self) -> dict[str, Any]:
        return {
            "type": "dashes_rover",
            "protocol": 1,
            "device_id": self.device_id,
            "name": "Dashes",
            "hostname": self.hostname,
            "http_port": self.http_port,
            "ws_port": self.http_port,
            "address": _local_ip(),
            "timestamp": int(time.time()),
        }

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._udp_loop, daemon=True, name="dashes-discovery"),
            threading.Thread(target=self._mdns_loop, daemon=True, name="dashes-mdns"),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads = []

    def _udp_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    data, address = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                try:
                    request = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if request.get("type") != "dashes_discover":
                    continue
                expected = str(request.get("device_id") or "").strip()
                if expected and expected != self.device_id:
                    continue
                response = json.dumps(self.payload(), ensure_ascii=False).encode("utf-8")
                try:
                    sock.sendto(response, address)
                except OSError:
                    break
        except OSError:
            pass
        finally:
            sock.close()

    def _mdns_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", MDNS_PORT))
            membership = socket.inet_aton(MDNS_GROUP) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    packet, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                if len(packet) < 12:
                    continue
                response = self._mdns_response(packet)
                if response:
                    try:
                        sock.sendto(response, (MDNS_GROUP, MDNS_PORT))
                    except OSError:
                        break
        except OSError:
            pass
        finally:
            sock.close()

    def _mdns_response(self, query: bytes) -> bytes | None:
        service = SERVICE_TYPE
        instance = f"Dashes-{self.device_id}.{service}"
        host = self.hostname
        if b"_dashes-rover" not in query and b"_services" not in query:
            return None
        txt_value = f"id={self.device_id}".encode("utf-8")
        txt = bytes([len(txt_value)]) + txt_value
        answers = b"".join(
            [
                _record(service, 12, _labels(instance)),
                _record(instance, 33, struct.pack("!HHH", 0, 0, self.http_port) + _labels(host)),
                _record(instance, 16, txt),
                _record(host, 1, socket.inet_aton(_local_ip())),
            ]
        )
        return struct.pack("!HHHHHH", 0, 0x8400, 0, 4, 0, 0) + answers


rover_discovery = RoverDiscoveryService()


def main() -> None:
    """Run discovery independently so the rover remains findable if HTTP fails."""
    stopped = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    rover_discovery.start()
    try:
        while not stopped.wait(1.0):
            pass
    finally:
        rover_discovery.stop()


if __name__ == "__main__":
    main()
