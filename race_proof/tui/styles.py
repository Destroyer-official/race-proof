"""Modern Professional Dark-Mode TUI Stylesheet for RaceProof."""

TUI_CSS = """
Screen {
    background: #090d16;
    color: #f1f5f9;
}

Header {
    background: #0f172a;
    color: #38bdf8;
    text-style: bold;
    border-bottom: solid #0284c7;
    height: 3;
}

Footer {
    background: #0f172a;
    color: #94a3b8;
    height: 1;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 1 2;
    background: #090d16;
}

Tabs {
    background: #0f172a;
    border-bottom: solid #1e293b;
    height: 3;
}

Tab {
    color: #94a3b8;
    text-style: bold;
    padding: 0 2;
}

Tab.-active {
    color: #38bdf8;
    background: #1e293b;
    border-bottom: tall #38bdf8;
}

/* Card Containers */
.card {
    background: #0f172a;
    border: solid #1e293b;
    border-title-color: #38bdf8;
    border-title-style: bold;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}

.card:hover {
    border: solid #38bdf8;
}

.row {
    height: auto;
    layout: horizontal;
    margin-bottom: 1;
}

.col {
    width: 1fr;
    height: auto;
    margin-right: 1;
}

/* Engine and Status Cards */
.engine-card {
    background: #131b2e;
    border: solid #1e293b;
    padding: 1 2;
    width: 1fr;
    height: auto;
    min-height: 7;
    max-height: 9;
    margin-right: 1;
}


.engine-card:hover {
    border: solid #38bdf8;
}

.engine-card-title {
    color: #38bdf8;
    text-style: bold;
    margin-bottom: 1;
}

.metric-title {
    color: #94a3b8;
    text-style: bold;
}

.metric-value {
    color: #38bdf8;
    text-style: bold;
}

.metric-value-green {
    color: #10b981;
    text-style: bold;
}

.metric-value-red {
    color: #f43f5e;
    text-style: bold;
}

.metric-value-yellow {
    color: #f59e0b;
    text-style: bold;
}

/* KPI Row in Benchmark */
.kpi-row {
    height: auto;
    layout: horizontal;
    margin-bottom: 1;
}

.kpi-box {
    background: #131b2e;
    border: solid #1e293b;
    padding: 1;
    width: 1fr;
    margin-right: 1;
    text-align: center;
}

.kpi-box:hover {
    border: solid #38bdf8;
}

.kpi-box-title {
    color: #94a3b8;
    text-style: bold;
}

.kpi-box-val {
    color: #10b981;
    text-style: bold;
}

/* Buttons and Action Bars */
.action-bar {
    height: auto;
    width: 100%;
    layout: horizontal;
    margin-bottom: 1;
    align-vertical: middle;
}

.action-bar Button {
    width: 1fr;
    min-width: 12;
    height: 3;
    margin-right: 1;
}

Button {

    min-width: 16;
    height: 3;
    margin-right: 1;
    text-style: bold;
    border: none;
    background: #1e293b;
    color: #e2e8f0;
}

Button:hover {
    background: #334155;
    color: #ffffff;
}

Button.-primary {
    background: #0284c7;
    color: #ffffff;
}

Button.-primary:hover {
    background: #38bdf8;
    color: #000000;
}

Button.-success {
    background: #059669;
    color: #ffffff;
}

Button.-success:hover {
    background: #10b981;
    color: #000000;
}

Button.-warning {
    background: #d97706;
    color: #ffffff;
}

Button.-warning:hover {
    background: #f59e0b;
    color: #000000;
}

Button.-error {
    background: #dc2626;
    color: #ffffff;
}

Button.-error:hover {
    background: #f43f5e;
    color: #ffffff;
}

/* Inputs & Selects */
Input {
    background: #131b2e;
    border: solid #1e293b;
    color: #ffffff;
    margin-bottom: 1;
    padding: 0 1;
}

Input:focus {
    border: solid #38bdf8;
}

Select {
    background: #131b2e;
    border: solid #1e293b;
    color: #ffffff;
    margin-bottom: 1;
}

Select:focus {
    border: solid #38bdf8;
}

/* Labels */
.info-label {
    color: #94a3b8;
    text-style: bold;
    margin-bottom: 1;
}

.dim-label {
    color: #64748b;
}

/* Verdict Display Panels */
.verdict-panel-confirmed {
    background: #200810;
    border: tall #f43f5e;
    padding: 1 2;
    margin-bottom: 1;
    color: #fda4af;
}

.verdict-panel-benign {
    background: #042013;
    border: tall #10b981;
    padding: 1 2;
    margin-bottom: 1;
    color: #6ee7b7;
}

.verdict-panel-uncertain {
    background: #241804;
    border: tall #f59e0b;
    padding: 1 2;
    margin-bottom: 1;
    color: #fde68a;
}

/* Data Tables */
DataTable {
    background: #0b0f19;
    border: solid #1e293b;
    height: 1fr;
    color: #f8fafc;
}

DataTable > .datatable--header {
    background: #131b2e;
    color: #38bdf8;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #0284c7;
    color: #ffffff;
    text-style: bold;
}

/* Rich Log stream */
RichLog {
    background: #060911;
    border: solid #1e293b;
    padding: 1;
    height: 1fr;
    color: #e2e8f0;
}

.code-viewer {
    height: 1fr;
    min-height: 10;
}

#prove-trace-table {
    height: 9;
    min-height: 7;
    margin-bottom: 1;
}

#prove-tla-log {
    height: 16;
    min-height: 10;
}

#hunt-code-viewer {
    height: 18;
    min-height: 10;
}

#agent-stream-log {
    height: 18;
    min-height: 10;
}

#verify-details {
    height: 16;
    min-height: 10;
}

.detail-pane {
    background: #131b2e;
    border: solid #1e293b;
    padding: 1;
    margin-top: 1;
    color: #e2e8f0;
    height: auto;
    min-height: 5;
}
"""
