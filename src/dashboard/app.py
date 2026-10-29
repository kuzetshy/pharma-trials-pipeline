"""PharmaInsight - Visual Analytics & GenAI Clinical Intelligence Dashboard.

Multi-tab Streamlit application delivering:
1. Executive Overview (Gold Analytical Marts & KPIs)
2. Clinical Trials Explorer (Silver Normalized Studies with Search & Filters)
3. GenAI Clinical Protocol Copilot (Structured Protocol Summaries via LLM)
"""

import json
import os

import pandas as pd
import streamlit as st

from src.dashboard.api_client import ApiClientError, PharmaApiClient
from src.dashboard.visuals import (
    plot_drug_landscape,
    plot_phase_distribution,
    plot_timeline_dynamics,
    plot_top_sponsors_breakdown,
)

# Page configuration
st.set_page_config(
    page_title="PharmaInsight | Clinical Intelligence Platform",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS styling for modern biotechnology aesthetics
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #0284c7;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    .kpi-card {
        background-color: rgba(2, 132, 199, 0.06);
        border: 1px solid rgba(2, 132, 199, 0.2);
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .kpi-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0284c7;
    }
    .kpi-label {
        font-size: 0.85rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        margin: 0.15rem;
        border-radius: 12px;
        background-color: rgba(14, 165, 233, 0.12);
        color: #0369a1;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .card-box {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        background-color: rgba(255, 255, 255, 0.02);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_api_client(base_url: str) -> PharmaApiClient:
    """Singleton-style API client factory with caching."""
    return PharmaApiClient(base_url=base_url)


# --- SIDEBAR CONFIGURATION ---
default_api_url = os.getenv("API_URL", "http://localhost:8000")
st.sidebar.markdown("### 🔬 PharmaInsight Platform")
st.sidebar.caption("Clinical Trials Medallion ELT, DuckDB & GenAI")

api_url_input = st.sidebar.text_input("Backend REST API URL", value=default_api_url)
client = get_api_client(api_url_input)

# Check API health
is_connected = client.is_alive()
if is_connected:
    st.sidebar.success("🟢 API Service Connected")
    try:
        health_data = client.get_health()
        marts_ok = sum(1 for v in health_data.get("marts_available", {}).values() if v)
        st.sidebar.markdown(f"**Data Marts Available**: `{marts_ok} / 3`")
        st.sidebar.markdown(f"**Bronze Batches**: `{health_data.get('bronze_files_count', 0)}`")
        st.sidebar.markdown(f"**Silver Trials**: `{health_data.get('silver_trials_count', 0):,}`")
    except ApiClientError:
        pass

    with st.sidebar.expander("🛡️ Data Quality Gate Status"):
        try:
            q_status = client.get_quality_status()
            silver_ok = q_status.get("silver_gate", {}).get("passed", False)
            gold_ok = q_status.get("gold_gate", {}).get("passed", False)
            st.markdown(f"**Silver Contracts**: {'✅ Passed' if silver_ok else '❌ Failed'}")
            st.markdown(f"**Gold Mart Contracts**: {'✅ Passed' if gold_ok else '❌ Failed'}")
            st.caption(f"Overall Gate Verdict: **{q_status.get('status')}**")
        except ApiClientError:
            st.caption("Quality gate status not reachable.")
else:
    st.sidebar.error("🔴 API Service Unreachable")
    st.sidebar.warning(
        f"Cannot connect to `{api_url_input}`.\n\n"
        "Please ensure the FastAPI service is running (`uvicorn src.api.main:app --port 8000` "
        "or `docker compose up api`)."
    )

if st.sidebar.button("🔄 Refresh Data Cache"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.caption("PharmaInsight v1.0.0 • Python 3.13 • DuckDB • FastAPI")


# --- MAIN HEADER ---
st.markdown('<div class="main-title">💊 PharmaInsight Intelligence Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Real-time Clinical Trials Analytics, Competitive Benchmarking & GenAI Protocol Copilot</div>',
    unsafe_allow_html=True,
)


if not is_connected:
    st.info(
        "💡 **API Offline Demonstration Mode**\n\n"
        f"The dashboard is currently disconnected from the REST backend at `{api_url_input}`. "
        "Start the API service via `python -m uvicorn src.api.main:app --port 8000` to enable live streaming of "
        "cleansed Parquet data and LLM summarization."
    )
    st.stop()


# --- TABS LAYOUT ---
tab1, tab2, tab3 = st.tabs([
    "📊 Executive Overview (Gold Marts)",
    "🔍 Clinical Trials Explorer (Silver)",
    "🧬 GenAI Protocol Copilot",
])


# ==============================================================================
# TAB 1: EXECUTIVE OVERVIEW (GOLD MARTS)
# ==============================================================================
with tab1:
    st.markdown("### 🏆 Pharmaceutical Sponsor Benchmarks & Market Landscape")

    # Fetch Mart Data
    try:
        sponsors_resp = client.get_sponsors(limit=100, min_trials=1)
        sponsors = sponsors_resp.get("items", [])
        total_sponsors = sponsors_resp.get("total", len(sponsors))

        drugs_resp = client.get_drugs(limit=100)
        drugs = drugs_resp.get("items", [])
        total_drugs = drugs_resp.get("total", len(drugs))

        timeline = client.get_timeline()
    except ApiClientError as e:
        st.error(f"Failed to fetch analytical marts: {e}")
        sponsors, drugs, timeline, total_sponsors, total_drugs = [], [], [], 0, 0

    # Top KPI Metrics Row
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    with kpi_col1:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-value">{total_sponsors:,}</div>'
            f'<div class="kpi-label">Sponsors Benchmarked</div></div>',
            unsafe_allow_html=True,
        )
    with kpi_col2:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-value">{total_drugs:,}</div>'
            f'<div class="kpi-label">Investigational Drugs</div></div>',
            unsafe_allow_html=True,
        )
    with kpi_col3:
        total_enrolled = sum(s.get("total_enrolled_patients", 0) or 0 for s in sponsors)
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-value">{int(total_enrolled):,}</div>'
            f'<div class="kpi-label">Total Patient Reach</div></div>',
            unsafe_allow_html=True,
        )
    with kpi_col4:
        durations = [t.get("avg_trial_duration_days") for t in timeline if t.get("avg_trial_duration_days")]
        avg_dur = (sum(durations) / len(durations)) if durations else 0
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-value">{int(avg_dur):,} d</div>'
            f'<div class="kpi-label">Avg Trial Duration</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Filter controls for sponsors
    f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
    with f_col1:
        sponsor_class_filter = st.selectbox(
            "Sponsor Class Filter",
            options=["ALL", "INDUSTRY", "OTHER", "NIH", "FED"],
            index=0,
        )
    with f_col2:
        min_trials_filter = st.slider("Minimum Sponsored Trials", min_value=1, max_value=20, value=2)
    with f_col3:
        top_n_sponsors = st.slider("Top Sponsors to Display", min_value=5, max_value=30, value=15)

    # Filter sponsors in-memory or refetch
    filtered_sponsors = [
        s for s in sponsors
        if s.get("total_trials", 0) >= min_trials_filter
        and (sponsor_class_filter == "ALL" or s.get("lead_sponsor_class") == sponsor_class_filter)
    ]

    # Chart 1: Top Sponsors Breakdown
    fig_sponsors = plot_top_sponsors_breakdown(filtered_sponsors, top_n=top_n_sponsors)
    st.plotly_chart(fig_sponsors, use_container_width=True)

    # Row 2: Drug Landscape & Timeline
    st.markdown("### 🧬 Molecule Modalities & Historical Dynamics")
    c1, c2 = st.columns([1, 1])

    with c1:
        fig_drugs = plot_drug_landscape(drugs, top_n=15)
        st.plotly_chart(fig_drugs, use_container_width=True)

    with c2:
        fig_timeline = plot_timeline_dynamics(timeline)
        st.plotly_chart(fig_timeline, use_container_width=True)

    # Data Tables Expander
    with st.expander("📋 View Gold Marts Raw Records"):
        tab_sp, tab_dr, tab_tl = st.tabs(["Sponsors Mart", "Drug Landscape Mart", "Timeline Mart"])
        with tab_sp:
            if sponsors:
                df_sp = pd.DataFrame(sponsors)
                st.dataframe(df_sp, use_container_width=True)
                st.download_button(
                    "Download Sponsors CSV",
                    df_sp.to_csv(index=False),
                    "mart_sponsor_benchmarks.csv",
                    "text/csv",
                )
        with tab_dr:
            if drugs:
                df_dr = pd.DataFrame(drugs)
                st.dataframe(df_dr, use_container_width=True)
                st.download_button(
                    "Download Drugs CSV",
                    df_dr.to_csv(index=False),
                    "mart_drug_landscape.csv",
                    "text/csv",
                )
        with tab_tl:
            if timeline:
                df_tl = pd.DataFrame(timeline)
                st.dataframe(df_tl, use_container_width=True)


# ==============================================================================
# TAB 2: CLINICAL TRIALS EXPLORER (SILVER LAYER)
# ==============================================================================
with tab2:
    st.markdown("### 🔍 Search & Explore Cleaned Clinical Trials")
    st.caption("Normalized studies from the Silver Parquet layer with relational conditions and interventions.")

    # Search & Filter Row
    s_col1, s_col2, s_col3, s_col4 = st.columns([3, 2, 2, 1])
    with s_col1:
        search_query = st.text_input(
            "Search Studies",
            placeholder="Search by keyword, NCT ID, drug, or gene (e.g. Pembrolizumab, HER2, NCT00567554)",
        )
    with s_col2:
        phase_options = ["ALL", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1", "NA"]
        selected_phase = st.selectbox("Trial Phase", options=phase_options, index=0)
    with s_col3:
        status_options = [
            "ALL",
            "RECRUITING",
            "COMPLETED",
            "ACTIVE_NOT_RECRUITING",
            "NOT_YET_RECRUITING",
            "TERMINATED",
            "WITHDRAWN",
        ]
        selected_status = st.selectbox("Study Status", options=status_options, index=0)
    with s_col4:
        limit_count = st.selectbox("Page Size", options=[20, 50, 100], index=0)

    # Query Silver Trials
    try:
        trials_resp = client.get_trials(
            limit=limit_count,
            offset=0,
            search=search_query if search_query else None,
            phase=selected_phase,
            status=selected_status,
        )
        trials_list = trials_resp.get("items", [])
        total_trials_found = trials_resp.get("total", len(trials_list))
    except ApiClientError as err:
        st.error(f"Error fetching trials: {err}")
        trials_list, total_trials_found = [], 0

    st.markdown(f"**Found {total_trials_found:,} matching trials** (Showing top {len(trials_list)}):")

    if trials_list:
        with st.expander("📊 View Phase Distribution of Current Results", expanded=False):
            fig_phase = plot_phase_distribution(trials_list)
            st.plotly_chart(fig_phase, use_container_width=True)

        df_trials = pd.DataFrame(trials_list)
        # Rename for cleaner table headers
        rename_map = {
            "nct_id": "NCT ID",
            "brief_title": "Title",
            "overall_status": "Status",
            "phase": "Phase",
            "lead_sponsor_name": "Lead Sponsor",
            "start_date": "Start Date",
            "enrollment_count": "Enrollment",
        }
        display_cols = [c for c in rename_map.keys() if c in df_trials.columns]
        st.dataframe(
            df_trials[display_cols].rename(columns=rename_map),
            use_container_width=True,
            hide_index=True,
        )

        # Detailed Study Protocol Inspector
        st.markdown("#### 🔬 Inspect Study Protocol Details")
        trial_nct_options = [t["nct_id"] for t in trials_list]
        selected_nct = st.selectbox("Select Study to Inspect", options=trial_nct_options)

        if selected_nct:
            try:
                detail = client.get_trial_detail(selected_nct)
            except ApiClientError as err:
                st.error(f"Failed to fetch detail for {selected_nct}: {err}")
                detail = None

            if detail:
                st.markdown(f"### {detail.get('brief_title')}")
                if detail.get("official_title"):
                    st.caption(f"**Official Title:** {detail.get('official_title')}")

                d_col1, d_col2, d_col3, d_col4 = st.columns(4)
                d_col1.metric("Status", detail.get("overall_status") or "N/A")
                d_col2.metric("Phase", detail.get("phase") or "N/A")
                d_col3.metric("Enrollment", f"{detail.get('enrollment_count') or 0:,}")
                d_col4.metric("Start Date", detail.get("start_date") or "N/A")

                # Conditions
                st.markdown("**Medical Indications & Conditions:**")
                conditions = detail.get("conditions", [])
                if conditions:
                    st.markdown(
                        " ".join([f'<span class="badge-pill">{c}</span>' for c in conditions]),
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No specific condition terms recorded.")

                # Interventions
                st.markdown("<br>**Investigational Interventions:**", unsafe_allow_html=True)
                interventions = detail.get("interventions", [])
                if interventions:
                    df_int = pd.DataFrame(interventions)
                    st.table(df_int)
                else:
                    st.caption("No interventions listed.")

                # Protocol Summary Text
                if detail.get("brief_summary"):
                    with st.expander("📄 Study Protocol Executive Summary"):
                        st.write(detail.get("brief_summary"))


# ==============================================================================
# TAB 3: GENAI CLINICAL PROTOCOL COPILOT
# ==============================================================================
with tab3:
    st.markdown("### 🧬 GenAI Clinical Protocol Summarizer")
    st.markdown(
        "Leverages AI with **Pydantic Structured Outputs** to synthesize clinical mechanisms of action, "
        "target patient populations, trial endpoints, and safety profiles from complex clinical protocols."
    )

    # Preset pickers for convenience
    preset_col1, preset_col2 = st.columns([3, 1])
    with preset_col1:
        # Default choices from current loaded trials
        candidate_ids = [t["nct_id"] for t in trials_list[:20]] if trials_list else ["NCT00567554"]
        target_nct_id = st.selectbox(
            "Select Trial Identifier (NCT ID)",
            options=candidate_ids,
            help="Choose from loaded studies or enter custom NCT ID below",
        )
    with preset_col2:
        custom_nct_input = st.text_input("Or enter custom NCT ID", placeholder="NCT12345678")

    chosen_nct = (custom_nct_input.strip().upper() if custom_nct_input else target_nct_id)

    # Quick preview of target study
    if chosen_nct:
        try:
            preview_study = client.get_trial_detail(chosen_nct)
        except ApiClientError:
            preview_study = None

        if preview_study:
            st.info(
                f"**Target Protocol:** {chosen_nct} — {preview_study.get('brief_title')} "
                f"({preview_study.get('lead_sponsor_name') or 'Sponsor Unspecified'})"
            )
        else:
            st.warning(f"Protocol '{chosen_nct}' was not found in the Silver layer repository.")

        # Action Button to trigger GenAI synthesis
        col_btn, _ = st.columns([2, 4])
        with col_btn:
            generate_clicked = st.button("✨ Generate AI Protocol Dossier", type="primary", use_container_width=True)

        if generate_clicked:
            with st.spinner(f"Contacting GenAI engine for {chosen_nct}... Analyzing protocol components..."):
                try:
                    summary_result = client.summarize_trial(chosen_nct)
                except ApiClientError as exc:
                    st.error(f"GenAI Summarization Failed: {exc}")
                    summary_result = None

            if summary_result:
                st.success("✅ Clinical Protocol Synthesis Generated Successfully!")

                # Provider Info Badge
                model_used = summary_result.get("model_name", "LLM Engine")
                st.markdown(
                    f'<span class="badge-pill" style="background-color: rgba(16, 185, 129, 0.15); color: #047857;">'
                    f'🤖 Generated via {model_used}</span>',
                    unsafe_allow_html=True,
                )

                st.markdown("<br>", unsafe_allow_html=True)

                # Dossier Sections
                st.markdown("#### 🎯 Mechanism of Action (MOA)")
                st.info(summary_result.get("mechanism_of_action") or "Not specified")

                st.markdown("#### 👥 Target Patient Population")
                st.write(summary_result.get("target_population") or "Not specified")

                r_col1, r_col2 = st.columns(2)
                with r_col1:
                    st.markdown("#### 🏆 Primary Clinical Endpoints")
                    endpoints = summary_result.get("primary_endpoints", [])
                    if endpoints:
                        for ep in endpoints:
                            st.markdown(f"- ✅ **{ep}**")
                    else:
                        st.caption("No specific endpoints synthesized.")

                with r_col2:
                    st.markdown("#### ⚠️ Key Safety & Adverse Event Risks")
                    risks = summary_result.get("key_risks", [])
                    if risks:
                        for risk in risks:
                            st.markdown(f"- ⚠️ {risk}")
                    else:
                        st.caption("No critical adverse risks noted.")

                if summary_result.get("design_summary"):
                    st.markdown("#### 📋 Protocol Design Synthesis")
                    st.write(summary_result.get("design_summary"))

                # Export Raw JSON
                with st.expander("📦 Export Synthesized JSON Dossier"):
                    st.json(summary_result)
                    st.download_button(
                        label="Download JSON Dossier",
                        data=json.dumps(summary_result, indent=2, ensure_ascii=False),
                        file_name=f"{chosen_nct}_clinical_summary.json",
                        mime="application/json",
                    )
