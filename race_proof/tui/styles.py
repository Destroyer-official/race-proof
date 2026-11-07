"""Cyber Dark-Mode TUI Stylesheet for RaceProof."""

TUI_CSS = """
Screen {
    background: #070b19;
    color: #e2e8f0;
}

Header {
    background: #0f172a;
    color: #00f0ff;
    text-style: bold;
    border-bottom: solid #00f0ff;
}

Footer {
    background: #0f172a;
    color: #94a3b8;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 1 2;
    background: #070b19;
}

Tabs {
    background: #0f172a;
    border-bottom: solid #1e293b;
}

Tab {
    color: #94a3b8;
    text-style: bold;
}

Tab.-active {
    color: #00f0ff;
    background: #1e293b;
    border-bottom: tall #00f0ff;
}

/* Common Containers */
.card {
    background: #0f172a;
    border: solid #1e293b;
    border-title-color: #00f0ff;
    border-title-style: bold;
    padding: 1;
    margin-bottom: 1;
}

.card:hover {
    border: solid #00f0ff;
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
    background: #0f172a;
    border: solid #334155;
    padding: 1;
    width: 1fr;
    margin-right: 1;
    text-align: center;
}

.metric-title {
    color: #94a3b8;
    text-style: bold;
}

.metric-value {
    color: #00f0ff;
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

/* Buttons */
Button {
    min-width: 16;
    height: 3;
    margin-right: 1;
    text-style: bold;
    border: none;
}

Button.-primary {
    background: #0284c7;
    color: #ffffff;
}

Button.-primary:hover {
    background: #00f0ff;
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
    background: #e11d48;
    color: #ffffff;
}

Button.-error:hover {
    background: #f43f5e;
    color: #000000;
}

/* Inputs & Selects */
Input {
    background: #1e293b;
    border: solid #334155;
    color: #ffffff;
    margin-bottom: 1;
}

Input:focus {
    border: solid #00f0ff;
}

Select {
    background: #1e293b;
    border: solid #334155;
    color: #ffffff;
    margin-bottom: 1;
}

/* Data Tables */
DataTable {
    background: #0f172a;
    border: solid #1e293b;
    height: 1fr;
    color: #f8fafc;
}

DataTable > .datatable--header {
    background: #1e293b;
    color: #00f0ff;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #0284c7;
    color: #ffffff;
    text-style: bold;
}

/* Rich Log stream */
RichLog {
    background: #050811;
    border: solid #1e293b;
    padding: 1;
    height: 1fr;
    color: #38bdf8;
}

/* Result Banners */
.banner-confirmed {
    background: #4c0519;
    border: tall #f43f5e;
    color: #fda4af;
    padding: 1;
    text-style: bold;
    margin-bottom: 1;
}

.banner-safe {
    background: #064e3b;
    border: tall #10b981;
    color: #a7f3d0;
    padding: 1;
    text-style: bold;
    margin-bottom: 1;
}

.banner-uncertain {
    background: #451a03;
    border: tall #f59e0b;
    color: #fde68a;
    padding: 1;
    text-style: bold;
    margin-bottom: 1;
}
"""

