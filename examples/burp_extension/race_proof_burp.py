# -*- coding: utf-8 -*-
"""
RaceProof - Burp Suite Python Extension (Jython compatible)

Allows one-click verification of concurrent race responses directly inside
Burp Suite (Intruder, Repeater, Logger, Proxy).
"""
import json
import os
import subprocess
import tempfile
import webbrowser
from datetime import datetime

from burp import IBurpExtender, IContextMenuFactory
from javax.swing import JMenuItem


class BurpExtender(IBurpExtender, IContextMenuFactory):

    def registerExtenderCallbacks(self, callbacks):
        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        callbacks.setExtensionName("RaceProof Verifier")
        callbacks.registerContextMenuFactory(self)
        print("[+] RaceProof Burp Extension loaded successfully.")
        print("[+] Right-click concurrent responses -> 'Verify with RaceProof'")

    def createMenuItems(self, invocation):
        messages = invocation.getSelectedMessages()
        if not messages or len(messages) < 2:
            return None

        menu_item = JMenuItem("⚡ Verify Race Condition with RaceProof ({0} items)".format(len(messages)))
        menu_item.addActionListener(lambda event: self._run_oracle(messages))
        return [menu_item]

    def _run_oracle(self, messages):
        entries = []
        for i, msg in enumerate(messages):
            req_info = self._helpers.analyzeRequest(msg)
            url = str(req_info.getUrl())
            method = req_info.getMethod()

            resp = msg.getResponse()
            if resp:
                resp_info = self._helpers.analyzeResponse(resp)
                status = resp_info.getStatusCode()
                body_offset = resp_info.getBodyOffset()
                body_bytes = resp[body_offset:]
                body_str = self._helpers.bytesToString(body_bytes)
            else:
                status = 200
                body_str = ""

            entries.append({
                "startedDateTime": datetime.utcnow().isoformat() + "Z",
                "time": 25.0,
                "request": {"method": method, "url": url},
                "response": {"status": status, "content": {"text": body_str}},
                "timings": {"send": 1.0, "wait": 23.0, "receive": 1.0}
            })

        har_payload = {
            "log": {
                "version": "1.2",
                "creator": {"name": "Burp RaceProof", "version": "1.0"},
                "entries": entries
            }
        }

        # Write temp HAR
        fd, har_path = tempfile.mkstemp(prefix="race_proof_", suffix=".har")
        with os.fdopen(fd, "w") as f:
            json.dump(har_payload, f)

        out_dir = os.path.join(tempfile.gettempdir(), "race_proof_findings_" + str(int(datetime.utcnow().timestamp())))
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        print("[+] Running RaceProof analysis on {0} responses...".format(len(messages)))

        try:
            # Spawn race-proof CLI
            subprocess.Popen([
                "race-proof", "verify",
                "-i", har_path,
                "-o", out_dir,
                "--no-agent"
            ])
            print("[+] Analysis initiated. Output directory: {0}".format(out_dir))
        except Exception as ex:
            print("[-] Error invoking race-proof: {0}".format(ex))

