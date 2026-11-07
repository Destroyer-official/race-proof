"""Evidence packager — creates a defensible PoC bundle.

Output structure:
    finding_<id>/
    ├── verdict.json          # structured verdict
    ├── requests/
    │   ├── baseline.http
    │   └── race_NN.http
    ├── responses/
    │   ├── baseline.txt
    │   └── race_NN.txt
    ├── diff.html             # visual body diff
    ├── timing_chart.png      # TTFB/elapsed distribution
    └── report.md             # human-readable, bug-bounty ready
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from race_proof.models import RaceSession, Verdict, VerdictLevel
from race_proof.evidence.poc_generator import PocGenerator


class EvidencePackager:
    """Creates a self-contained evidence bundle for a finding."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or Path.cwd() / "race_proof_findings"

    def package(self, session: RaceSession, verdict: Verdict) -> Path:
        """Create the full evidence bundle. Returns the bundle directory path."""
        bundle_dir = self.output_dir / f"finding_{verdict.finding_id}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        (bundle_dir / "requests").mkdir(exist_ok=True)
        (bundle_dir / "responses").mkdir(exist_ok=True)

        # 1. Verdict JSON
        self._write_verdict_json(bundle_dir, verdict)

        # 2. Requests
        self._write_requests(bundle_dir, session)

        # 3. Responses
        self._write_responses(bundle_dir, session)

        # 4. Visual diff (HTML)
        self._write_diff_html(bundle_dir, session, verdict)

        # 5. Timing chart
        self._write_timing_chart(bundle_dir, session)

        # 6. Markdown report
        self._write_report_md(bundle_dir, session, verdict)

        # 7. Automated Asynchronous Python PoC
        self._write_poc_script(bundle_dir, session, verdict)

        # 8. Enterprise SARIF 2.1.0 Standard
        self._write_sarif(bundle_dir, session, verdict)

        # 9. Cryptographically Signed in-toto / Sigstore Attestation
        self._write_attestation(bundle_dir, session, verdict)

        # Update verdict with bundle path
        verdict.evidence_bundle_path = str(bundle_dir)

        return bundle_dir

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    def _write_verdict_json(self, bundle_dir: Path, verdict: Verdict) -> None:
        (bundle_dir / "verdict.json").write_text(
            json.dumps(verdict.as_report_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _write_requests(self, bundle_dir: Path, session: RaceSession) -> None:
        req_dir = bundle_dir / "requests"

        if session.baseline.request:
            (req_dir / "baseline.http").write_text(
                session.baseline.request.raw, encoding="utf-8"
            )

        for resp in session.race_responses:
            if resp.request:
                fname = f"race_{resp.sequence_index:02d}.http"
                (req_dir / fname).write_text(resp.request.raw, encoding="utf-8")

    def _write_responses(self, bundle_dir: Path, session: RaceSession) -> None:
        resp_dir = bundle_dir / "responses"

        def fmt_response(resp: Any, label: str) -> str:
            lines = [
                f"# {label}",
                f"Status: {resp.status_code}",
                f"Elapsed: {resp.elapsed_ms:.1f} ms",
                f"TTFB: {resp.ttfb_ms:.1f} ms" if resp.ttfb_ms is not None else "",
                "",
                "## Headers",
            ]
            for k, v in (resp.headers or {}).items():
                lines.append(f"{k}: {v}")
            lines.extend(["", "## Body", resp.body or "(empty)"])
            return "\n".join(l for l in lines if l is not None)

        (resp_dir / "baseline.txt").write_text(
            fmt_response(session.baseline, "Baseline Response"), encoding="utf-8"
        )
        for resp in session.race_responses:
            fname = f"race_{resp.sequence_index:02d}.txt"
            (resp_dir / fname).write_text(
                fmt_response(resp, f"Race Response [{resp.sequence_index}]"),
                encoding="utf-8",
            )

    def _write_diff_html(self, bundle_dir: Path, session: RaceSession, verdict: Verdict) -> None:
        html_content = self._build_dashboard_html(session, verdict)
        (bundle_dir / "diff.html").write_text(html_content, encoding="utf-8")

    def _build_dashboard_html(self, session: RaceSession, verdict: Verdict) -> str:
        import html
        import difflib

        def format_body(b: str) -> str:
            if not b:
                return "(empty body)"
            try:
                parsed = json.loads(b)
                return json.dumps(parsed, indent=2)
            except Exception:
                return b

        base_raw = format_body(session.baseline.body)
        winner = session.winner_candidates[0] if session.winner_candidates else session.race_responses[0]
        winner_raw = format_body(winner.body)

        base_lines = base_raw.splitlines()
        winner_lines = winner_raw.splitlines()

        matcher = difflib.SequenceMatcher(None, base_lines, winner_lines)
        diff_rows: list[str] = []

        for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
            if tag == "equal":
                for i in range(ahi - alo):
                    diff_rows.append(
                        f'<tr><td class="ln">{alo + i + 1}</td><td class="code">{html.escape(base_lines[alo + i])}</td>'
                        f'<td class="ln">{blo + i + 1}</td><td class="code">{html.escape(winner_lines[blo + i])}</td></tr>'
                    )
            elif tag == "replace":
                max_len = max(ahi - alo, bhi - blo)
                for i in range(max_len):
                    left_text = html.escape(base_lines[alo + i]) if alo + i < ahi else ""
                    left_ln = str(alo + i + 1) if alo + i < ahi else ""
                    right_text = html.escape(winner_lines[blo + i]) if blo + i < bhi else ""
                    right_ln = str(blo + i + 1) if blo + i < bhi else ""
                    diff_rows.append(
                        f'<tr class="diff-mod"><td class="ln">{left_ln}</td><td class="code del">{left_text}</td>'
                        f'<td class="ln">{right_ln}</td><td class="code add">{right_text}</td></tr>'
                    )
            elif tag == "delete":
                for i in range(alo, ahi):
                    diff_rows.append(
                        f'<tr class="diff-del"><td class="ln">{i + 1}</td><td class="code del">{html.escape(base_lines[i])}</td>'
                        f'<td class="ln"></td><td class="code"></td></tr>'
                    )
            elif tag == "insert":
                for i in range(blo, bhi):
                    diff_rows.append(
                        f'<tr class="diff-add"><td class="ln"></td><td class="code"></td>'
                        f'<td class="ln">{i + 1}</td><td class="code add">{html.escape(winner_lines[i])}</td></tr>'
                    )

        diff_table_html = "\n".join(diff_rows)

        # Build Waterfall SVG
        all_resps = [session.baseline] + session.race_responses
        max_time = max([r.elapsed_ms for r in all_resps] or [10.0])
        if max_time <= 0:
            max_time = 1.0

        svg_w = 700
        bar_x_start = 150
        bar_max_w = 450
        row_h = 28
        svg_h = len(all_resps) * row_h + 30

        svg_bars: list[str] = []
        for idx, r in enumerate(all_resps):
            y = 20 + idx * row_h
            is_base = (idx == 0)
            label = "Baseline" if is_base else f"Race [{r.sequence_index}]"
            stat = f"HTTP {r.status_code}"
            elapsed = r.elapsed_ms
            ttfb = r.ttfb_ms if r.ttfb_ms is not None else elapsed * 0.7

            ttfb_w = max(2, int((ttfb / max_time) * bar_max_w))
            total_w = max(4, int((elapsed / max_time) * bar_max_w))
            proc_w = max(2, total_w - ttfb_w)

            bar_color = "#38bdf8" if is_base else ("#ef4444" if r.status_code in (200, 201) and not is_base and verdict.is_confirmed else "#818cf8")

            svg_bars.append(f'''
              <text x="10" y="{y + 14}" fill="#94a3b8" font-size="12" font-family="monospace">{label} ({stat})</text>
              <rect x="{bar_x_start}" y="{y + 2}" width="{ttfb_w}" height="16" rx="3" fill="#0284c7" opacity="0.8">
                <title>TTFB: {ttfb:.1f}ms</title>
              </rect>
              <rect x="{bar_x_start + ttfb_w}" y="{y + 2}" width="{proc_w}" height="16" rx="3" fill="{bar_color}">
                <title>Server Processing: {max(0.0, elapsed - ttfb):.1f}ms</title>
              </rect>
              <text x="{bar_x_start + total_w + 8}" y="{y + 14}" fill="#cbd5e1" font-size="11" font-family="monospace">{elapsed:.1f}ms</text>
            ''')

        svg_html = f'''
        <svg width="100%" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" style="background:#0f172a; border-radius:8px; border:1px solid #1e293b;">
          <line x1="{bar_x_start}" y1="10" x2="{bar_x_start}" y2="{svg_h - 10}" stroke="#334155" stroke-dasharray="2 2" />
          <line x1="{bar_x_start + bar_max_w}" y1="10" x2="{bar_x_start + bar_max_w}" y2="{svg_h - 10}" stroke="#334155" stroke-dasharray="2 2" />
          {"".join(svg_bars)}
        </svg>
        '''

        # Violations HTML
        violations_html = ""
        if verdict.invariant_violations:
            items = []
            for v in verdict.invariant_violations:
                items.append(f'''
                  <div style="background:#1e1b4b; border-left:4px solid #ef4444; padding:12px; margin-bottom:8px; border-radius:4px;">
                    <span style="background:#ef4444; color:#fff; font-size:10px; font-weight:bold; padding:2px 6px; border-radius:3px; margin-right:8px;">{v.severity}</span>
                    <strong style="color:#f8fafc; font-family:monospace;">{html.escape(v.rule_id)}</strong>: <span style="color:#cbd5e1;">{html.escape(v.description)}</span>
                    <div style="margin-top:6px; font-size:12px; color:#94a3b8; font-family:monospace;">
                      Evidence: <code>{html.escape(str(v.evidence))}</code>
                    </div>
                  </div>
                ''')
            violations_html = f'''
            <div style="background:#090d16; border:1px solid #dc2626; border-radius:8px; padding:18px; margin-bottom:20px;">
              <h3 style="margin-top:0; color:#ef4444; font-size:16px;">🚨 Invariant Violations Detected ({len(verdict.invariant_violations)})</h3>
              {"".join(items)}
            </div>
            '''

        # Defect Diagnosis Card (2027 Research Layer: IEEE S&P 2025 Racedb / ANSI SQL)
        defect_html = ""
        if verdict.concurrency_defect_class:
            defect_html = f'''
            <div style="background: #0f172a; border: 1px solid #38bdf8; border-radius: 8px; padding: 18px; margin-bottom: 24px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-size: 13px; font-weight: 700; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.5px;">
                  🔬 Academic Concurrency Diagnosis (IEEE S&P 2025 / ANSI SQL)
                </span>
                <span style="background: #0284c7; color: #fff; font-family: monospace; font-size: 12px; font-weight: bold; padding: 3px 8px; border-radius: 4px;">
                  {html.escape(verdict.concurrency_defect_class)}
                </span>
              </div>
              <div style="color: #cbd5e1; font-size: 14px; margin-bottom: 8px;">
                <strong>Isolation Vulnerability:</strong> {html.escape(verdict.isolation_level_implication or "Unspecified")}
              </div>
              <div style="color: #34d399; font-size: 13px; background: rgba(16, 185, 129, 0.1); padding: 10px; border-radius: 6px; border-left: 3px solid #10b981;">
                <strong>Defensive Remediation:</strong> {html.escape(verdict.remediation_guidance or "Apply transactional locks")}
              </div>
            </div>
            '''

        verdict_theme = {
            VerdictLevel.CONFIRMED: ("#ef4444", "rgba(239, 68, 68, 0.15)", "🔴 CONFIRMED VULNERABILITY"),
            VerdictLevel.UNCERTAIN: ("#f59e0b", "rgba(245, 158, 11, 0.15)", "🟡 UNCERTAIN — DEEPER TRIALS REQUIRED"),
            VerdictLevel.NOISE: ("#10b981", "rgba(16, 185, 129, 0.15)", "🟢 NOISE — NO INVARIANTS VIOLATED"),
        }.get(verdict.verdict, ("#64748b", "rgba(100, 116, 139, 0.15)", "UNKNOWN"))

        color, bg_glow, title_badge = verdict_theme

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RaceProof Audit — {html.escape(verdict.finding_id)}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #090d16;
      color: #e2e8f0;
      margin: 0;
      padding: 24px;
    }}
    .header {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 20px {bg_glow};
    }}
    .badge {{
      display: inline-block;
      padding: 6px 14px;
      border-radius: 6px;
      font-weight: 700;
      font-size: 14px;
      background: {color};
      color: #fff;
      letter-spacing: 0.5px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .tile {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 16px;
    }}
    .tile-title {{
      font-size: 12px;
      color: #64748b;
      text-transform: uppercase;
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .tile-value {{
      font-size: 22px;
      font-weight: 700;
      color: #f8fafc;
      font-family: monospace;
    }}
    .section-title {{
      font-size: 18px;
      font-weight: 600;
      color: #f1f5f9;
      margin-top: 32px;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .diff-table {{
      width: 100%;
      border-collapse: collapse;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      background: #0b1120;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #1e293b;
    }}
    .diff-table th {{
      background: #1e293b;
      padding: 10px 14px;
      text-align: left;
      font-weight: 600;
      color: #94a3b8;
    }}
    .diff-table td {{
      padding: 3px 8px;
      vertical-align: top;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    .ln {{
      width: 40px;
      text-align: right;
      color: #475569;
      user-select: none;
      padding-right: 12px;
      border-right: 1px solid #1e293b;
    }}
    .code {{
      padding-left: 12px;
      color: #cbd5e1;
    }}
    .code.add {{
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
    }}
    .code.del {{
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
    }}
    .diff-mod {{
      background: rgba(245, 158, 11, 0.08);
    }}
    .poc-box {{
      background: #020617;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 14px;
      font-family: monospace;
      color: #38bdf8;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .copy-btn {{
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 4px;
      padding: 6px 12px;
      cursor: pointer;
      font-size: 12px;
      font-weight: bold;
    }}
    .copy-btn:hover {{
      background: #1d4ed8;
    }}
  </style>
</head>
<body>

  <div class="header">
    <div>
      <h1 style="margin:0 0 6px 0; font-size:22px; color:#f8fafc;">RaceProof Verification Audit</h1>
      <div style="color:#64748b; font-family:monospace; font-size:13px;">Finding: {html.escape(verdict.finding_id)} | Tool: {html.escape(session.tool_source)}</div>
    </div>
    <div>
      <span class="badge">{title_badge}</span>
    </div>
  </div>

  <div class="grid">
    <div class="tile">
      <div class="tile-title">Confidence</div>
      <div class="tile-value" style="color:{color};">{verdict.confidence:.1%}</div>
    </div>
    <div class="tile">
      <div class="tile-title">Success Rate</div>
      <div class="tile-value">{verdict.success_rate:.1%}</div>
    </div>
    <div class="tile">
      <div class="tile-title">Wilson Score 95% CI</div>
      <div class="tile-value">[{verdict.ci_95_lower:.1%}, {verdict.ci_95_upper:.1%}]</div>
    </div>
    <div class="tile">
      <div class="tile-title">Severity Rating</div>
      <div class="tile-value" style="color:{color};">{verdict.severity_hint}</div>
    </div>
  </div>

  {defect_html}

  {violations_html}

  <div class="section-title">⏱️ Concurrency Flight Window Waterfall</div>
  {svg_html}

  <div class="section-title">⚖️ Differential Response Comparison (Baseline vs Winner)</div>
  <table class="diff-table">
    <thead>
      <tr>
        <th colspan="2">Baseline Response ({session.baseline.status_code})</th>
        <th colspan="2">Race Response [{winner.sequence_index}] ({winner.status_code})</th>
      </tr>
    </thead>
    <tbody>
      {diff_table_html}
    </tbody>
  </table>

  <div class="section-title">🧪 Reproduction Test Harness</div>
  <div class="poc-box">
    <span>python reproduce_race.py</span>
    <button class="copy-btn" onclick="navigator.clipboard.writeText('python reproduce_race.py'); this.innerText='Copied!'; setTimeout(()=>this.innerText='Copy', 2000);">Copy</button>
  </div>

</body>
</html>
'''

    def _write_timing_chart(self, bundle_dir: Path, session: RaceSession) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            elapsed = [r.elapsed_ms for r in session.race_responses]
            baseline_elapsed = session.baseline.elapsed_ms

            fig, ax = plt.subplots(figsize=(10, 4))
            indices = list(range(len(elapsed)))
            ax.bar(indices, elapsed, color="#2196F3", alpha=0.7, label="Race responses")
            ax.axhline(y=baseline_elapsed, color="#f44336", linewidth=2,
                       linestyle="--", label=f"Baseline ({baseline_elapsed:.1f} ms)")
            ax.set_xlabel("Race Response Index")
            ax.set_ylabel("Elapsed Time (ms)")
            ax.set_title(f"Timing Distribution — {session.id}")
            ax.legend()
            ax.grid(axis="y", alpha=0.3)
            plt.tight_layout()
            plt.savefig(bundle_dir / "timing_chart.png", dpi=120, bbox_inches="tight")
            plt.close(fig)
        except Exception:
            # matplotlib may not be available or fail in headless mode
            (bundle_dir / "timing_chart.png").write_bytes(b"")

    def _write_report_md(self, bundle_dir: Path, session: RaceSession, verdict: Verdict) -> None:
        verdict_emoji = {
            VerdictLevel.CONFIRMED: "🔴",
            VerdictLevel.UNCERTAIN: "🟡",
            VerdictLevel.NOISE: "🟢",
        }[verdict.verdict]

        lines: list[str] = [
            f"# Race Condition Finding — {verdict.finding_id}",
            f"",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Tool Source:** {session.tool_source}",
            f"",
            f"---",
            f"",
            f"## {verdict_emoji} Verdict: {verdict.verdict.value}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Confidence | {verdict.confidence:.1%} |",
            f"| Success Rate | {verdict.success_rate:.1%} |",
            f"| 95% CI | [{verdict.ci_95_lower:.1%} – {verdict.ci_95_upper:.1%}] |",
            f"| p-value | {verdict.p_value:.4f} |",
            f"| Trials | {verdict.trial_count} |",
            f"| Severity | **{verdict.severity_hint}** |",
            f"| Invariant Violated | {verdict.invariant_violated or 'None detected'} |",
            f"",
        ]

        if verdict.invariant_violations:
            lines += [
                f"## Invariant Violations",
                f"",
            ]
            for v in verdict.invariant_violations:
                lines += [
                    f"### [{v.severity}] `{v.rule_id}`",
                    f"{v.description}",
                    f"",
                    f"**Evidence:** {v.evidence}",
                    f"",
                ]

        if verdict.concurrency_defect_class:
            lines += [
                f"## 🔬 Concurrency Defect Classification (IEEE S&P 2025 / ANSI SQL)",
                f"",
                f"- **Defect Class:** `{verdict.concurrency_defect_class}`",
                f"- **Isolation Flaw:** {verdict.isolation_level_implication}",
                f"- **Recommended Defense:** {verdict.remediation_guidance}",
                f"",
            ]

        lines += [
            f"## Analysis Dimensions",
            f"",
            f"| Dimension | Anomaly | Confidence | Summary |",
            f"|-----------|---------|------------|---------|",
        ]
        for dim in verdict.dimensions:
            icon = "✅" if dim.anomaly_detected else "✗"
            lines.append(
                f"| {dim.dimension.value} | {icon} | {dim.confidence:.1%} | {dim.summary[:80]} |"
            )

        lines += [
            f"",
            f"## Evidence",
            f"",
        ]
        for dim in verdict.dimensions:
            if dim.evidence_lines:
                lines += [f"### {dim.dimension.value}", ""]
                for ev in dim.evidence_lines[:5]:
                    lines.append(f"- {ev}")
                lines.append("")

        lines += [
            f"## Reproduction",
            f"",
            f"See `reproduce_race.py` for a standalone executable Python reproduction script.",
            f"See `requests/` for the exact HTTP requests that produced this finding.",
            f"See `responses/` for the captured responses.",
            f"See `diff.html` for a visual body comparison.",
            f"See `timing_chart.png` for the response timing distribution.",
            f"",
            f"---",
            f"*Generated by RaceProof v0.1.0*",
        ]

        (bundle_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_poc_script(self, bundle_dir: Path, session: RaceSession, verdict: Verdict) -> None:
        poc_code = PocGenerator.generate(session, verdict)
        (bundle_dir / "reproduce_race.py").write_text(poc_code, encoding="utf-8")

    def _write_sarif(self, bundle_dir: Path, session: RaceSession, verdict: Verdict) -> None:
        from race_proof.evidence.sarif import SarifExporter
        SarifExporter.write_sarif(session, verdict, bundle_dir / "sarif.json")

    def _write_attestation(self, bundle_dir: Path, session: RaceSession, verdict: Verdict) -> None:
        from race_proof.evidence.attestation import AttestationSigner
        AttestationSigner.write_attestation(bundle_dir, session, verdict)

