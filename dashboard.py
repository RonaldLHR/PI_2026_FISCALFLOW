from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx


DB_PATH = Path(__file__).with_name("historico_downloads.db")


def _running_under_streamlit() -> bool:
    return get_script_run_ctx() is not None


if __name__ == "__main__" and not _running_under_streamlit():
    print("Este dashboard deve ser iniciado com: streamlit run dashboard.py")
    sys.exit(0)


st.set_page_config(
    page_title="BergBot Dashboard",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=30)
def load_data(db_path: str) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=["id", "filename", "data_download"])

    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT id, filename, data_download
                FROM logs_xml
                ORDER BY data_download DESC, id DESC
                """,
                conn,
            )
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return pd.DataFrame(columns=["id", "filename", "data_download"])

    if df.empty:
        return df

    df["data_download"] = pd.to_datetime(df["data_download"], errors="coerce")
    df = df.dropna(subset=["data_download"])
    return df


def main() -> None:
    st.title("📊 BergBot Dashboard")
    st.caption("Monitoramento dos downloads de XML armazenados no SQLite.")

    df = load_data(str(DB_PATH))

    if df.empty:
        st.error(
            f"Nenhum dado encontrado. Verifique se o banco {DB_PATH.name} existe e se a tabela logs_xml foi criada pelo bot."
        )
        return

    df = df.sort_values(["data_download", "id"], ascending=False).reset_index(drop=True)

    min_date = df["data_download"].min().date()
    max_date = df["data_download"].max().date()

    st.sidebar.header("Filtros")
    start_date = st.sidebar.date_input("Data Inicial", value=min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("Data Final", value=max_date, min_value=min_date, max_value=max_date)
    search_text = st.sidebar.text_input("Buscar arquivo XML", value="").strip().lower()

    if start_date > end_date:
        st.sidebar.warning("A Data Inicial não pode ser maior que a Data Final.")
        st.stop()

    filtered_df = df[
        (df["data_download"].dt.date >= start_date)
        & (df["data_download"].dt.date <= end_date)
    ].copy()

    if search_text:
        filtered_df = filtered_df[
            filtered_df["filename"].astype(str).str.lower().str.contains(search_text, na=False)
        ]

    total_xmls = int(df.shape[0])
    xmls_filtrados = int(filtered_df.shape[0])

    col1, col2 = st.columns(2)
    col1.metric("Total de XMLs Baixados", total_xmls)
    col2.metric("XMLs Filtrados", xmls_filtrados)

    st.divider()

    chart_df = (
        filtered_df.assign(dia=filtered_df["data_download"].dt.date)
        .groupby("dia", as_index=False)
        .size()
        .rename(columns={"size": "quantidade"})
        .sort_values("dia")
    )

    if not chart_df.empty:
        fig = px.bar(
            chart_df,
            x="dia",
            y="quantidade",
            text="quantidade",
            title="Quantidade de XMLs baixados por dia",
            labels={"dia": "Data", "quantidade": "XMLs"},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            template="plotly_white",
            height=420,
            margin=dict(l=20, r=20, t=60, b=20),
            xaxis_title=None,
            yaxis_title="Quantidade",
        )
        fig.update_xaxes(tickformat="%d/%m/%Y")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nenhum registro encontrado para os filtros selecionados.")

    st.subheader("Tabela de downloads")
    if filtered_df.empty:
        st.info("Nenhum XML corresponde aos filtros atuais.")
    else:
        table_df = filtered_df.loc[:, ["id", "filename", "data_download"]].copy()
        table_df["data_download"] = table_df["data_download"].dt.strftime("%d/%m/%Y %H:%M:%S")
        table_df = table_df.rename(
            columns={
                "id": "ID",
                "filename": "Nome do Arquivo",
                "data_download": "Data/Hora",
            }
        )
        st.dataframe(table_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
