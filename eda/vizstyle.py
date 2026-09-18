"""Shared matplotlib styling so every chart in every EDA notebook matches.

Values come from the project's validated light-mode palette. Import and call
`apply()` once per notebook; use SERIES for categorical marks and BLUES for
magnitude (choropleths, heatmaps).
"""

from __future__ import annotations

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap

# --- chrome & ink ---------------------------------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

# --- categorical slots, assigned in fixed order, never cycled -------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#8b5fbf"]  # blue, orange, aqua, violet

# --- sequential ramp for magnitude ---------------------------------------
# Single hue, light -> dark. Lightest step means "near zero".
_BLUE_STEPS = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]
BLUES = LinearSegmentedColormap.from_list("project_blues", _BLUE_STEPS)

# --- diverging ramp for polarity (net flow, deltas) -----------------------
# Two poles that read as opposite, with a NEUTRAL GRAY midpoint so zero reads
# as "nothing" rather than as a third category. Never a hue at the midpoint.
NEUTRAL = "#f0efec"
DIVERGING = LinearSegmentedColormap.from_list(
    "project_diverging",
    ["#0d366b", "#256abf", "#5598e7", "#9ec5f4", NEUTRAL,
     "#f3a3a2", "#e87a79", "#e34948", "#a82322"],
)


def apply() -> None:
    """Set rcParams. Recessive grid and axes; the data carries the emphasis."""
    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 120,

        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 13,

        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK,
        "axes.titlesize": 15,
        "axes.titleweight": "medium",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.labelsize": 13,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": mpl.cycler(color=SERIES),

        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "xtick.direction": "out",
        "ytick.direction": "out",

        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.grid": True,
        "axes.grid.axis": "y",

        "lines.linewidth": 2.0,
        "lines.markersize": 8,

        "legend.frameon": False,
        "legend.fontsize": 12,
        "legend.labelcolor": INK_SECONDARY,
    })
