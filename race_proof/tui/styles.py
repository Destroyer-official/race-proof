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

/* Metric Tiles */
.metric-tile {
    background: #131b2e;
    border: solid #1e293b;
    padding: 1;
    width: 1fr;
    margin-right: 1;
    text-align: center;
}

.metric-tile:hover {
    border: solid #38bdf8;
}

.metric-title {
    color: #64748b;
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

.kpi-box-title {
    color: #64748b;
    text-style: bold;
}

.kpi-box-val {
    color: #10b981;
    text-style: bold;
}

/* Buttons */
.action-bar {
    height: auto;
    layout: horizontal;
    margin-bottom: 1;
    align-vertical: middle;
}

Button {
    min-width: 18;
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
    min-height: 12;
}

.detail-pane {
    background: #131b2e;
    border: solid #1e293b;
    padding: 1;
    margin-top: 1;
    color: #e2e8f0;
}
"""
