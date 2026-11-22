#!/usr/bin/env python3
"""Record the public Mech Royale spectator feed to replay files. Standard library only.

    python3 tools/feed_record.py                      # wss://watch.joinbuilders.org/live -> replays/feed/
    python3 tools/feed_record.py --out DIR --url URL  # other feed / folder
    python3 tools/feed_record.py --minutes 120        # stop after 2 h (default: run until Ctrl-C)

The watch page's stage opens a WebSocket to /live and receives newline-separated JSON lines in the
"mechreplay/1" format (a "header" line, then one frame per line, then a "result" line). Each match is
written to its own gzip file, `<UTC time>-seed<seed>.jsonl.gz`, from its header to its result. A file
without a result line means the stream dropped mid-match. Reconnects on its own (like the page, every
second). Read the files with tools/feed_analyze.py.

Runs on any machine with Python 3.8+. Not from a cloud session whose proxy can't upgrade to WebSocket.
"""
import argparse
import base64
import gzip
import json
import os
import socket
import ssl
import struct
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class WS:
    """Minimal RFC 6455 client: text/binary messages, fragmentation, ping/pong, close."""

    def __init__(self, url, timeout=30.0):
        u = urlparse(url)
        self.host, secure = u.hostname, u.scheme == "wss"
        port = u.port or (443 if secure else 80)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        raw = socket.create_connection((self.host, port), timeout=timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host) if secure else raw
        key = base64.b64encode(os.urandom(16)).decode()
        origin = ("https://" if secure else "http://") + self.host
        req = (f"GET {path} HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n"
               f"User-Agent: mech-royale-feed-recorder\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during handshake")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status + " ":
            raise ConnectionError(f"handshake refused: {status}")

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytes([0x80 | opcode])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self):
        """Next complete text/binary message as str; None when the server closes."""
        parts = []
        while True:
            b0, b1 = self._read(2)
            fin, op, masked, n = b0 & 0x80, b0 & 0x0F, b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if masked else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 8:                       # close
                try:
                    self._send(8, data[:2])
                except OSError:
                    pass
                return None
            if op == 9:                       # ping -> pong
                self._send(10, data)
                continue
            if op == 10:                      # pong
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self._send(8, struct.pack(">H", 1000))
        except OSError:
            pass
        self.sock.close()


class Writer:
    """One gzip file per match: opened on a header line, closed on the result line (or a new header)."""

    def __init__(self, out):
        self.out, self.f, self.path, self.lines, self.saved = out, None, None, 0, 0
        os.makedirs(out, exist_ok=True)

    def line(self, text):
        try:
            o = json.loads(text)
        except ValueError:
            return
        kind = o.get("type") if isinstance(o, dict) else None
        if kind == "header":
            self.finish(complete=False)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.path = os.path.join(self.out, f"{stamp}-seed{o.get('seed', 'x')}.jsonl.gz")
            self.f = gzip.open(self.path, "wt")
            names = [m.get("name") for m in o.get("mechs", [])]
            print(f"[{stamp}] match start seed {o.get('seed')}: {len(names)} mechs: {', '.join(map(str, names))}", flush=True)
        if self.f is None:
            return                            # joined mid-match: wait for the next header
        self.f.write(text.strip() + "\n")
        self.lines += 1
        if kind == "result":
            self.finish(complete=True)

    def finish(self, complete):
        if self.f is None:
            return
        self.f.close()
        if complete:
            self.saved += 1
            print(f"  saved {self.path} ({self.lines} lines)", flush=True)
        else:
            os.replace(self.path, self.path.replace(".jsonl.gz", ".partial.jsonl.gz"))
            print(f"  stream ended mid-match: kept as .partial ({self.lines} lines)", flush=True)
        self.f, self.lines = None, 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="wss://watch.joinbuilders.org/live")
    ap.add_argument("--out", default=os.path.join(ROOT, "replays", "feed"))
    ap.add_argument("--minutes", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    a = ap.parse_args()
    w = Writer(a.out)
    stop = time.time() + a.minutes * 60 if a.minutes else None
    print(f"recording {a.url} -> {a.out}", flush=True)
    try:
        while stop is None or time.time() < stop:
            try:
                ws = WS(a.url)
                print("connected", flush=True)
                while stop is None or time.time() < stop:
                    msg = ws.recv()
                    if msg is None:
                        break
                    for text in msg.split("\n"):
                        if text.strip():
                            w.line(text)
                ws.close()
            except (OSError, ConnectionError, ssl.SSLError) as e:
                print(f"disconnected: {e}; retrying in 1 s", flush=True)
            w.finish(complete=False)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    w.finish(complete=False)
    print(f"done: {w.saved} complete match(es) in {a.out}")


if __name__ == "__main__":
    main()
