"""
Streamlit dashboard for Rider Churn Early Warning System.

Views:
1. Country/City overview — fleet health heatmap
2. City deep dive — ranked list of at-risk couriers
3. Courier detail — individual risk profile with explanations and actions
4. Model performance — metrics, feature importance, validation results
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# --- Page Config ---
st.set_page_config(
    page_title="Rider Churn Early Warning",
    page_icon="⚠️",
    layout="wide",
)


def main():
    st.title("⚠️ Rider Churn Early Warning System")
    st.markdown("Identify at-risk couriers before they leave. Act early, retain more.")

    # --- Sidebar: Filters ---
    with st.sidebar:
        st.header("Filters")
        selected_country = st.selectbox("Country", ["All", "Poland", "Ukraine"])
        selected_city = st.selectbox("City", ["All", "Warsaw", "Kyiv"])
        selected_segment = st.multiselect(
            "Courier Segment",
            ["Newbie", "Active", "Veteran"],
            default=["Newbie", "Active", "Veteran"],
        )
        risk_threshold = st.slider("Risk Threshold", 0.0, 1.0, 0.5, 0.05)

    # --- Tab Layout ---
    tab1, tab2, tab3, tab4 = st.tabs([
        "🌍 Fleet Overview",
        "🏙️ City Deep Dive",
        "👤 Courier Detail",
        "📊 Model Performance",
    ])

    with tab1:
        render_fleet_overview()

    with tab2:
        render_city_deep_dive()

    with tab3:
        render_courier_detail()

    with tab4:
        render_model_performance()


def render_fleet_overview():
    """Country/city level summary with risk heatmap."""
    st.subheader("Fleet Health Overview")

    # TODO: Load predictions and aggregate by city
    # Columns: City | Active Couriers | High Risk | % At Risk | Predicted Fleet in 30d

    st.info("🔨 Connect to prediction pipeline to populate this view")

    # Placeholder metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Active Couriers", "—")
    col2.metric("High Risk", "—", delta="—")
    col3.metric("Predicted Fleet (30d)", "—")
    col4.metric("Avg Churn Probability", "—")

    # TODO: City comparison chart
    # fig = px.bar(city_summary, x="city", y="high_risk_pct", color="high_risk_pct")
    # st.plotly_chart(fig, use_container_width=True)


def render_city_deep_dive():
    """Ranked list of at-risk couriers for selected city."""
    st.subheader("City Deep Dive")

    # TODO: Show ranked table of couriers
    # Columns: Rank | Courier ID | Segment | Churn Prob | Top Driver | Recommended Action
    st.info("🔨 Connect to prediction pipeline to populate this view")

    # TODO: Distribution chart of churn probabilities for the city
    # fig = px.histogram(predictions, x="churn_probability", nbins=30)
    # st.plotly_chart(fig, use_container_width=True)


def render_courier_detail():
    """Individual courier risk profile."""
    st.subheader("Courier Detail")

    # TODO: Courier search/selector
    courier_id = st.text_input("Enter Courier ID")

    if courier_id:
        # TODO: Load courier's prediction, features, and SHAP explanation
        st.info(f"🔨 Load profile for courier {courier_id}")

        # Show: churn probability gauge, top risk factors, trend charts,
        # recommended actions, courier metadata

        # SHAP waterfall chart for this courier
        # Action recommendations from src.actions.recommendations


def render_model_performance():
    """Model metrics, feature importance, validation results."""
    st.subheader("Model Performance")

    # TODO: Load evaluation metrics
    st.info("🔨 Connect to evaluation pipeline to populate this view")

    # Feature importance bar chart
    # ROC curve
    # Precision-Recall curve
    # Performance by segment (newbie vs active vs veteran)
    # Confusion matrix


if __name__ == "__main__":
    main()
