"""Interactive Plotly chart components for PharmaInsight visual analytics."""

from typing import Any

import plotly.graph_objects as go

# Professional medical/biotech color palette
PALETTE = {
    "primary": "#0284c7",      # Sky blue
    "secondary": "#0d9488",    # Teal
    "accent": "#6366f1",       # Indigo
    "warning": "#f59e0b",      # Amber
    "success": "#10b981",      # Emerald
    "danger": "#ef4444",       # Rose/Red
    "gray": "#64748b",         # Slate
    "background": "rgba(0,0,0,0)",
}


def plot_top_sponsors_breakdown(sponsors: list[dict[str, Any]], top_n: int = 15) -> go.Figure:
    """Create horizontal stacked/grouped bar chart of top clinical trial sponsors."""
    if not sponsors:
        fig = go.Figure()
        fig.update_layout(title="No sponsor data available")
        return fig

    sorted_sponsors = sorted(sponsors, key=lambda x: x.get("total_trials", 0), reverse=True)[:top_n]
    names = [s.get("lead_sponsor_name", "Unknown")[:30] for s in reversed(sorted_sponsors)]
    total_trials = [s.get("total_trials", 0) for s in reversed(sorted_sponsors)]
    active = [s.get("active_trials", 0) for s in reversed(sorted_sponsors)]
    phase3 = [s.get("phase_3_trials", 0) for s in reversed(sorted_sponsors)]
    enrolled = [s.get("total_enrolled_patients", 0) or 0 for s in reversed(sorted_sponsors)]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            y=names,
            x=total_trials,
            name="Total Trials",
            orientation="h",
            marker=dict(color="#0284c7"),
            hovertemplate="<b>%{y}</b><br>Total Trials: %{x}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            y=names,
            x=active,
            name="Active Trials",
            orientation="h",
            marker=dict(color="#10b981"),
            hovertemplate="<b>%{y}</b><br>Active Trials: %{x}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            y=names,
            x=phase3,
            name="Phase 3 Trials",
            orientation="h",
            marker=dict(color="#6366f1"),
            customdata=enrolled,
            hovertemplate="<b>%{y}</b><br>Phase 3 Trials: %{x}<br>Enrolled Patients: %{customdata:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"🏆 Top {len(sorted_sponsors)} Pharmaceutical Sponsors by Clinical Activity",
        barmode="group",
        xaxis_title="Number of Clinical Trials",
        yaxis_title="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=20, t=60, b=30),
        height=max(450, len(sorted_sponsors) * 32),
        hovermode="closest",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.2)")
    return fig


def plot_drug_landscape(drugs: list[dict[str, Any]], top_n: int = 15) -> go.Figure:
    """Create bar chart of top clinical interventions and patient reach."""
    if not drugs:
        fig = go.Figure()
        fig.update_layout(title="No drug landscape data available")
        return fig

    sorted_drugs = sorted(drugs, key=lambda x: x.get("total_trials_count", 0), reverse=True)[:top_n]
    names = [d.get("intervention_name", "Unknown")[:25] for d in sorted_drugs]
    counts = [d.get("total_trials_count", 0) for d in sorted_drugs]
    patient_reach = [d.get("total_patient_reach", 0) or 0 for d in sorted_drugs]
    itypes = [d.get("intervention_type", "OTHER") for d in sorted_drugs]

    type_colors = {
        "DRUG": "#0284c7",
        "BIOLOGICAL": "#0d9488",
        "RADIATION": "#f59e0b",
        "PROCEDURE": "#8b5cf6",
        "GENETIC": "#ec4899",
        "OTHER": "#64748b",
    }
    colors = [type_colors.get(t, "#64748b") for t in itypes]

    fig = go.Figure(
        go.Bar(
            x=names,
            y=counts,
            customdata=list(zip(itypes, patient_reach, strict=False)),
            marker=dict(color=colors),
            hovertemplate="<b>%{x}</b><br>Modality: %{customdata[0]}<br>Trials Count: %{y}<br>Patient Reach: %{customdata[1]:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"🧬 Top {len(sorted_drugs)} Investigational Interventions by Adoption",
        xaxis_title="",
        yaxis_title="Clinical Trials Count",
        margin=dict(l=20, r=20, t=50, b=80),
        height=450,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(tickangle=-35, showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.2)")
    return fig


def plot_timeline_dynamics(timeline: list[dict[str, Any]]) -> go.Figure:
    """Create dual-axis chart with annual trials launched and average duration."""
    if not timeline:
        fig = go.Figure()
        fig.update_layout(title="No timeline data available")
        return fig

    # Group by start_year (aggregating counts across study types)
    yearly_data: dict[int, dict[str, Any]] = {}
    for item in timeline:
        year = item.get("start_year")
        if not year or year < 2000:
            continue
        if year not in yearly_data:
            yearly_data[year] = {"year": year, "started": 0, "completed": 0, "durations": []}
        yearly_data[year]["started"] += item.get("trials_started_count", 0)
        yearly_data[year]["completed"] += item.get("completed_count", 0)
        dur = item.get("avg_trial_duration_days")
        if dur:
            yearly_data[year]["durations"].append(dur)

    sorted_years = sorted(yearly_data.keys())
    if not sorted_years:
        fig = go.Figure()
        fig.update_layout(title="No recent timeline data (post-2000)")
        return fig

    years = [str(y) for y in sorted_years]
    started = [yearly_data[y]["started"] for y in sorted_years]
    completed = [yearly_data[y]["completed"] for y in sorted_years]
    avg_duration = [
        (sum(yearly_data[y]["durations"]) / len(yearly_data[y]["durations"]))
        if yearly_data[y]["durations"]
        else None
        for y in sorted_years
    ]

    fig = go.Figure()

    # Bar: Trials Started
    fig.add_trace(
        go.Bar(
            x=years,
            y=started,
            name="Trials Initiated",
            marker=dict(color="#0284c7"),
            hovertemplate="Year %{x}: %{y} trials initiated<extra></extra>",
        )
    )

    # Bar: Completed
    fig.add_trace(
        go.Bar(
            x=years,
            y=completed,
            name="Trials Completed",
            marker=dict(color="#10b981"),
            hovertemplate="Year %{x}: %{y} trials completed<extra></extra>",
        )
    )

    # Line on Secondary Y-Axis: Duration
    fig.add_trace(
        go.Scatter(
            x=years,
            y=avg_duration,
            name="Avg Duration (Days)",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color="#f59e0b", width=3),
            marker=dict(size=7),
            hovertemplate="Year %{x}: %{y:.0f} days avg duration<extra></extra>",
        )
    )

    fig.update_layout(
        title="📈 Historical Trial Initiations vs Average Duration Over Time",
        barmode="stack",
        xaxis=dict(title="Year of Launch", tickangle=-45),
        yaxis=dict(title="Number of Trials", showgrid=True, gridcolor="rgba(128,128,128,0.2)"),
        yaxis2=dict(
            title="Avg Duration (Days)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=40, t=60, b=50),
        height=450,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def plot_phase_distribution(trials: list[dict[str, Any]]) -> go.Figure:
    """Create donut chart showing study phase distribution."""
    if not trials:
        fig = go.Figure()
        fig.update_layout(title="No phase data")
        return fig

    phase_counts: dict[str, int] = {}
    for t in trials:
        ph = t.get("phase") or "NOT APPLICABLE"
        phase_counts[ph] = phase_counts.get(ph, 0) + 1

    labels = list(phase_counts.keys())
    values = list(phase_counts.values())

    colors = [
        "#38bdf8",  # Phase 1
        "#0284c7",  # Phase 2
        "#6366f1",  # Phase 3
        "#8b5cf6",  # Phase 4
        "#10b981",  # Early Phase 1
        "#94a3b8",  # N/A
    ]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.45,
                marker=dict(colors=colors),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Count: %{value} (%{percent})<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        title="🔬 Phase Distribution Breakdown",
        showlegend=False,
        margin=dict(l=20, r=20, t=50, b=20),
        height=380,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
