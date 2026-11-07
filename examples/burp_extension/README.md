# RaceProof — Burp Suite Extension Integration

Pipes race attack results directly from Burp Suite into RaceProof's verification engine with a single right-click.

---

## Capabilities

- **Direct Context Menu Integration**: Select responses in Burp Intruder, Repeater, Logger, or Proxy, right-click and choose **"⚡ Verify Race Condition with RaceProof"**.
- **Automated Differential Extraction**: Extracts HTTP status codes, headers, response bodies, and timing latencies into an RFC-compliant HAR stream.
- **Browser Launch**: Automatically opens the interactive dark-mode visual audit dashboard (`diff.html`) with concurrency waterfall graphs and invariant violation evidence.

---

## Option 1: Modern Java Montoya API Extension (Recommended)

### Requirements
- Burp Suite v2023.12 or newer
- JDK 17+ and Gradle

### Build & Install
1. Build the JAR:
   ```bash
   cd examples/burp_extension
   gradle jar
   ```
2. Open Burp Suite $\to$ **Extensions** $\to$ **Installed** $\to$ **Add**.
3. Choose **Extension type: Java** and select `build/libs/race-proof-burp-0.1.0.jar`.

---

## Option 2: Python / Jython Extension (Zero Compilation)

### Requirements
- Burp Suite with Jython standalone configured in **Extensions** $\to$ **Options** $\to$ **Python Environment**.

### Install
1. Open Burp Suite $\to$ **Extensions** $\to$ **Installed** $\to$ **Add**.
2. Choose **Extension type: Python** and select `race_proof_burp.py`.

---

## Usage Workflow

1. Send concurrent requests with Burp Intruder (e.g. Single-Packet Attack or Turbo Intruder).
2. Highlight the responses in Intruder or Logger table (at least 2 responses).
3. Right-click $\to$ **"⚡ Verify Race Condition with RaceProof"**.
4. RaceProof runs in the background; the interactive HTML dashboard opens automatically in your browser.

