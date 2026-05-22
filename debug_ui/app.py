import hashlib
import json
import os
import re
import altair as alt
import pandas as pd
from deltalake import DeltaTable
import streamlit as st

# Helper functions for processing and testability


def load_delta_table(path: str) -> pd.DataFrame | None:
    """Loads a Delta table from path and returns a Pandas DataFrame, or None if invalid."""
    if not path or not os.path.exists(path):
        return None
    if not DeltaTable.is_deltatable(path):
        return None
    try:
        dt = DeltaTable(path)
        return dt.to_pandas()
    except Exception:
        return None


def get_dockets(df: pd.DataFrame) -> list[str]:
    """Extracts sorted, unique docket IDs from the DataFrame if the column exists."""
    if df is None or df.empty:
        return []
    if "docket_id" in df.columns:
        return sorted(df["docket_id"].dropna().unique().astype(str).tolist())
    return []


def get_disk_size_mb(path: str) -> float:
    """Recursively computes disk size of a directory or file in MB."""
    if not path or not os.path.exists(path):
        return 0.0
    total_size = 0
    if os.path.isdir(path):
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
                except OSError:
                    pass
    else:
        try:
            total_size = os.path.getsize(path)
        except OSError:
            pass
    return round(total_size / (1024 * 1024), 2)


def get_overview_stats(df: pd.DataFrame, docket_id: str | None, path: str) -> dict:
    """Computes basic overview statistics for a given docket in the DataFrame."""
    stats = {
        "total_rows": 0,
        "unique_comment_id_count": 0,
        "duplicate_comment_id_count": 0,
        "posted_date_range": (None, None),
        "last_modified_date_range": (None, None),
        "received_date_range": (None, None),
        "attachment_count": 0,
        "null_empty_text_count": 0,
        "disk_size_mb": get_disk_size_mb(path),
        "text_col_found": None,
    }

    if df is None or df.empty:
        return stats

    df_docket = df
    if docket_id and "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == docket_id]

    stats["total_rows"] = len(df_docket)
    if stats["total_rows"] == 0:
        return stats

    # Unique & Duplicate Comment IDs
    if "comment_id" in df_docket.columns:
        unique_count = df_docket["comment_id"].nunique()
        stats["unique_comment_id_count"] = unique_count
        stats["duplicate_comment_id_count"] = max(0, stats["total_rows"] - unique_count)

    # Date ranges
    for col in ["posted_date", "last_modified_date", "received_date"]:
        if col in df_docket.columns:
            series = pd.to_datetime(df_docket[col], errors="coerce").dropna()
            if not series.empty:
                stats[f"{col}_range"] = (series.min(), series.max())

    # Attachment counts
    if "has_attachments" in df_docket.columns:
        series = df_docket["has_attachments"]
        if series.dtype == bool:
            stats["attachment_count"] = int(series.sum())
        else:
            stats["attachment_count"] = int(series.astype(bool).sum())

    # Detect text field
    candidate_text_cols = ["comment_text", "text", "body", "raw_text", "parsed_text"]
    text_col = None
    for col in candidate_text_cols:
        if col in df_docket.columns:
            text_col = col
            break

    if text_col:
        stats["text_col_found"] = text_col
        series = df_docket[text_col]
        null_count = series.isna().sum()
        empty_count = (series.dropna().astype(str).str.strip() == "").sum()
        stats["null_empty_text_count"] = int(null_count + empty_count)

    return stats


def get_exact_hash_baseline_stats(
    df: pd.DataFrame | None, docket_id: str | None
) -> dict:
    """Computes exact-hash baseline metrics for substantive comments of a given docket."""
    stats = {
        "substantive_rows": 0,
        "duplicate_hash_groups": 0,
        "exact_duplicate_comments_covered": 0,
        "largest_exact_duplicate_group": 0,
        "exact_duplicate_coverage_pct": 0.0,
    }

    if df is None or df.empty:
        return stats

    df_docket = df
    if docket_id and "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == docket_id]

    if df_docket.empty:
        return stats

    # Filter to detail_comment_text (substantive comments)
    if "text_source" in df_docket.columns:
        df_sub = df_docket[df_docket["text_source"] == "detail_comment_text"]
    else:
        df_sub = df_docket

    stats["substantive_rows"] = len(df_sub)

    if stats["substantive_rows"] == 0:
        return stats

    if "normalized_text_hash" in df_sub.columns:
        hashes = df_sub["normalized_text_hash"].dropna()
        hashes = hashes[hashes.astype(str).str.strip() != ""]

        if not hashes.empty:
            hash_counts = hashes.value_counts()
            dup_hashes = hash_counts[hash_counts > 1]

            stats["duplicate_hash_groups"] = len(dup_hashes)
            stats["exact_duplicate_comments_covered"] = int(dup_hashes.sum())
            stats["largest_exact_duplicate_group"] = (
                int(dup_hashes.max()) if not dup_hashes.empty else 0
            )
            stats["exact_duplicate_coverage_pct"] = round(
                (stats["exact_duplicate_comments_covered"] / stats["substantive_rows"])
                * 100,
                2,
            )

    return stats


def get_duplicate_text_stats(
    df: pd.DataFrame, docket_id: str | None, text_col: str
) -> pd.DataFrame:
    """Computes exact duplicate normalized text counts for a specific column."""
    if df is None or df.empty or text_col not in df.columns:
        return pd.DataFrame(columns=["hash", "count", "sample_text"])

    df_docket = df
    if docket_id and "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == docket_id]

    texts = df_docket[text_col].dropna().astype(str).str.strip()
    texts = texts[texts != ""]
    if texts.empty:
        return pd.DataFrame(columns=["hash", "count", "sample_text"])

    # Normalize: lowercase and collapse all whitespace
    normalized = texts.apply(lambda x: re.sub(r"\s+", " ", x.lower()))

    # Hash each normalized text
    hashes = normalized.apply(lambda x: hashlib.sha256(x.encode("utf-8")).hexdigest())

    # Map hash -> first original text as a sample
    hash_to_sample = {}
    for text_val, h in zip(texts, hashes):
        if h not in hash_to_sample:
            hash_to_sample[h] = text_val

    hash_counts = hashes.value_counts()
    duplicates = hash_counts[hash_counts > 1]

    if duplicates.empty:
        return pd.DataFrame(columns=["hash", "count", "sample_text"])

    res_df = pd.DataFrame(
        {
            "hash": duplicates.index,
            "count": duplicates.values,
            "sample_text": [hash_to_sample[h] for h in duplicates.index],
        }
    )
    return res_df


def get_records_per_day(
    df: pd.DataFrame, docket_id: str | None, date_col: str = "last_modified_date"
) -> pd.DataFrame:
    """Groups record count per day by date_col."""
    if df is None or df.empty or date_col not in df.columns:
        return pd.DataFrame(columns=["date", "count"])

    df_docket = df
    if docket_id and "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == docket_id]

    series = pd.to_datetime(df_docket[date_col], errors="coerce").dropna()
    if series.empty:
        return pd.DataFrame(columns=["date", "count"])

    dates = series.dt.date
    counts = dates.value_counts().sort_index()
    res_df = pd.DataFrame({"date": counts.index, "count": counts.values})
    return res_df


def filter_by_docket(df: pd.DataFrame | None, docket_id: str | None) -> pd.DataFrame:
    """Returns rows for a docket when a docket_id column is available."""
    if df is None or df.empty:
        return pd.DataFrame()
    if docket_id and "docket_id" in df.columns:
        return df[df["docket_id"] == docket_id]
    return df


def value_counts_df(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Returns a two-column count table for a column, or an empty frame."""
    if df.empty or column not in df.columns:
        return pd.DataFrame(columns=[column, "count"])
    counts = df[column].dropna().astype(str).value_counts().reset_index()
    counts.columns = [column, "count"]
    return counts


def unique_values(df: pd.DataFrame, column: str) -> list:
    """Returns sorted non-null unique values for a column."""
    if df.empty or column not in df.columns:
        return []
    return sorted(df[column].dropna().unique().tolist())


def available_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    """Returns the requested columns that are present in the DataFrame."""
    if df.empty:
        return []
    return [col for col in columns if col in df.columns]


def add_text_preview(
    members_df: pd.DataFrame, parsed_df: pd.DataFrame | None
) -> pd.DataFrame:
    """Adds a best-effort parsed text preview to cluster membership rows."""
    if members_df.empty or parsed_df is None or parsed_df.empty:
        return members_df
    if "comment_id" not in members_df.columns or "comment_id" not in parsed_df.columns:
        return members_df

    text_cols = [
        col for col in ["raw_text", "normalized_text"] if col in parsed_df.columns
    ]
    if not text_cols:
        return members_df

    parsed_preview = parsed_df[["comment_id", *text_cols]].copy()
    parsed_preview["text_preview"] = ""
    for col in text_cols:
        parsed_preview["text_preview"] = parsed_preview["text_preview"].mask(
            parsed_preview["text_preview"].astype(str).str.strip() == "",
            parsed_preview[col],
        )
    parsed_preview["text_preview"] = (
        parsed_preview["text_preview"].fillna("").astype(str).str.slice(0, 300)
    )
    return members_df.merge(
        parsed_preview[["comment_id", "text_preview"]], on="comment_id", how="left"
    )


# Streamlit UI


def run_app():
    st.set_page_config(page_title="Bronze & Silver Delta Lake Debug UI", layout="wide")
    st.title("AstroTurf medaillon Debug UI")
    st.caption(
        "Internal developer tool for visually inspecting bronze raw ingestion, details enrichment, and silver attachment cataloging."
    )
    st.info(
        "**Medallion Architecture Check:** Bronze stores raw regulations.gov list-endpoint records. "
        "ParserAgent v2A enriches silver tables by fetching individual comment detail JSON bodies, cataloging attachments, "
        "and detecting boilerplate cover notes."
    )

    # Sidebar inputs
    st.sidebar.header("UI Inputs")
    bronze_path = st.sidebar.text_input(
        "Bronze Table Path", value="./data/bronze/raw_comments"
    )
    silver_path = st.sidebar.text_input(
        "Silver Table Path", value="./data/silver/parsed_comments"
    )
    details_path = st.sidebar.text_input(
        "Details Table Path", value="./data/silver/comment_details"
    )
    attachments_path = st.sidebar.text_input(
        "Attachments Table Path", value="./data/silver/comment_attachments"
    )
    embeddings_path = st.sidebar.text_input(
        "Embeddings Table Path", value="./data/silver/comment_embeddings"
    )
    clusters_path = st.sidebar.text_input(
        "Clusters Table Path", value="./data/gold/comment_clusters"
    )
    memberships_path = st.sidebar.text_input(
        "Cluster Memberships Table Path",
        value="./data/gold/comment_cluster_memberships",
    )
    row_limit = st.sidebar.selectbox("Row Limit", options=[25, 100, 500, 1000], index=0)

    df = load_delta_table(bronze_path)

    if df is None:
        st.sidebar.error("Could not load Delta Table.")
        st.error(f"### ERROR: No Delta table found at `{bronze_path}`")
        st.write(
            "Please run ingestion first to populate the table. Use the commands below in PowerShell:"
        )
        st.code(
            "uv run python scripts/run_ingestion.py --docket FDA-2013-S-0610",
            language="powershell",
        )
        return

    # Load silver/gold tables globally for docket mapping and downstream panels
    df_silver = load_delta_table(silver_path)
    df_details = load_delta_table(details_path)
    df_attachments = load_delta_table(attachments_path)
    df_embeddings = load_delta_table(embeddings_path)
    df_clusters = load_delta_table(clusters_path)
    df_memberships = load_delta_table(memberships_path)

    # Extract available dockets
    dockets = get_dockets(df)
    selected_docket_id = None
    if dockets:
        selected_docket_id = st.sidebar.selectbox("Select Docket ID", options=dockets)
    else:
        st.sidebar.warning("No 'docket_id' column or no dockets found.")

    manual_docket_id = st.sidebar.text_input("Fallback Manual Docket ID", value="")

    # Active docket logic
    active_docket = (
        manual_docket_id.strip() if manual_docket_id.strip() else selected_docket_id
    )

    if not active_docket:
        st.warning("Please select or type a Docket ID to inspect.")
        return

    # Filter dataframe by selected docket
    df_docket = df
    if "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == active_docket]

    st.write(f"### Active Docket ID: `{active_docket}`")

    # Filter details and attachments by active docket
    df_details_docket = None
    if df_details is not None and not df_details.empty:
        if "docket_id" in df_details.columns:
            df_details_docket = df_details[df_details["docket_id"] == active_docket]

    df_attachments_docket = None
    if df_attachments is not None and not df_attachments.empty:
        if "docket_id" in df_attachments.columns:
            df_attachments_docket = df_attachments[
                df_attachments["docket_id"] == active_docket
            ]

    df_silver_docket = filter_by_docket(df_silver, active_docket)
    df_embeddings_docket = filter_by_docket(df_embeddings, active_docket)
    df_clusters_docket = filter_by_docket(df_clusters, active_docket)
    df_memberships_docket = filter_by_docket(df_memberships, active_docket)

    # Overview panel
    stats = get_overview_stats(df, active_docket, bronze_path)

    st.subheader("Overview Panel")

    # Bronze health status check
    total_rows = stats["total_rows"]
    dup_ids = stats["duplicate_comment_id_count"]
    uniq_ids = stats["unique_comment_id_count"]
    if total_rows > 0 and dup_ids == 0 and uniq_ids == total_rows:
        st.success("Bronze health: OK")
    else:
        st.warning("Bronze health: Check diagnostics.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**Total Rows:** {stats['total_rows']}")
        st.markdown(f"**Unique Comment IDs:** {stats['unique_comment_id_count']}")
        st.markdown(f"**Duplicate Comment IDs:** {stats['duplicate_comment_id_count']}")
    with col2:
        posted_range = stats["posted_date_range"]
        st.markdown(
            f"**Min Posted Date:** {posted_range[0] if posted_range[0] else 'N/A'}"
        )
        st.markdown(
            f"**Max Posted Date:** {posted_range[1] if posted_range[1] else 'N/A'}"
        )
    with col3:
        modified_range = stats["last_modified_date_range"]
        st.markdown(
            f"**Min Last Modified:** {modified_range[0] if modified_range[0] else 'N/A'}"
        )
        st.markdown(
            f"**Max Last Modified:** {modified_range[1] if modified_range[1] else 'N/A'}"
        )
    with col4:
        st.markdown(f"**Attachment Count:** {stats['attachment_count']}")
        st.markdown(f"**Null/Empty Text Count:** {stats['null_empty_text_count']}")
        st.markdown(f"**Disk Size:** {stats['disk_size_mb']} MB")

    if stats["total_rows"] == 0:
        st.info("No records found for the selected docket ID.")
        return

    # Data preview
    st.subheader("Data Preview")

    expected_preview_cols = [
        "comment_id",
        "docket_id",
        "title",
        "comment_text",
        "posted_date",
        "last_modified_date",
        "received_date",
        "has_attachments",
    ]
    preview_cols = [col for col in expected_preview_cols if col in df_docket.columns]

    json_candidate_cols = ["attributes_json", "raw_json", "metadata_json"]
    for col in df_docket.columns:
        if col not in preview_cols:
            if (
                col in json_candidate_cols
                or col.endswith("_json")
                or col.startswith("raw_")
                or col == "metadata"
            ):
                preview_cols.append(col)

    st.write(f"Columns in Preview: `{', '.join(preview_cols)}`")

    search_query = st.text_input("Search Title or ID in preview", value="")
    df_preview = df_docket[preview_cols]

    if search_query:
        search_filter = pd.Series(False, index=df_preview.index)
        for col in ["comment_id", "title"]:
            if col in df_preview.columns:
                search_filter = search_filter | df_preview[col].dropna().astype(
                    str
                ).str.contains(search_query, case=False)
        df_preview = df_preview[search_filter]

    st.dataframe(df_preview.head(row_limit), use_container_width=True)

    # JSON Preview
    st.subheader("JSON Metadata & Detail Inspector")
    inspector_mode = st.radio(
        "Select JSON Inspector Source:",
        ["Bronze attributes_json", "Silver raw_detail_json (Enriched)"],
    )

    if inspector_mode == "Bronze attributes_json":
        json_col_to_use = None
        for col in json_candidate_cols:
            if col in df_docket.columns:
                json_col_to_use = col
                break

        if not json_col_to_use:
            for col in df_docket.columns:
                if col.endswith("_json") or col == "metadata":
                    json_col_to_use = col
                    break

        if json_col_to_use:
            st.write(f"Displaying JSON from column: `{json_col_to_use}`")
            if "comment_id" in df_docket.columns:
                comment_ids = df_docket["comment_id"].dropna().unique()
                selected_cid = st.selectbox(
                    "Select Comment ID to inspect JSON metadata", options=comment_ids
                )
                if selected_cid:
                    row_data = df_docket[df_docket["comment_id"] == selected_cid]
                    if not row_data.empty:
                        val = row_data[json_col_to_use].iloc[0]
                        try:
                            if isinstance(val, str):
                                parsed_json = json.loads(val)
                            else:
                                parsed_json = val
                            st.json(parsed_json)
                        except Exception as e:
                            st.warning(f"Could not parse JSON: {e}")
                            st.text(val)
        else:
            st.info("No JSON metadata column available.")
    else:
        if df_details_docket is not None and not df_details_docket.empty:
            comment_ids = df_details_docket["comment_id"].dropna().unique()
            selected_cid = st.selectbox(
                "Select Comment ID to inspect detail JSON payload", options=comment_ids
            )
            if selected_cid:
                row_data = df_details_docket[
                    df_details_docket["comment_id"] == selected_cid
                ]
                if not row_data.empty:
                    val = row_data["raw_detail_json"].iloc[0]
                    try:
                        if isinstance(val, str):
                            parsed_json = json.loads(val)
                        else:
                            parsed_json = val
                        st.json(parsed_json)
                    except Exception as e:
                        st.warning(f"Could not parse JSON: {e}")
                        st.text(val)
        else:
            st.info("No enriched comment details available. Run ParserAgent v2A first.")

    # White-box diagnostics
    st.subheader("White-Box Diagnostics")

    diag_tab1, diag_tab2, diag_tab3, diag_tab4, diag_tab5 = st.tabs(
        [
            "Records Per Day",
            "Null Count & Schema",
            "Duplicate comment_id Rows",
            "Sample Raw Records",
            "Comment Attachments Catalog",
        ]
    )

    with diag_tab1:
        st.write("#### Records per day by last_modified_date")
        if "last_modified_date" in df_docket.columns:
            daily_df = get_records_per_day(df, active_docket, "last_modified_date")
            if not daily_df.empty:
                daily_df = daily_df.copy()
                daily_df["date"] = daily_df["date"].astype(str)

                chart = (
                    alt.Chart(daily_df)
                    .mark_bar()
                    .encode(
                        x=alt.X("date:O", title="Date"),
                        y=alt.Y(
                            "count:Q",
                            title="Record Count",
                            scale=alt.Scale(domainMin=0),
                        ),
                    )
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No valid records with last_modified_date found.")
        else:
            st.info("last_modified_date column not available in DataFrame.")

    with diag_tab2:
        st.write("#### Schema & Null Counts")
        null_counts = df_docket.isna().sum()
        schema_df = pd.DataFrame(
            {
                "Column Name": df_docket.columns,
                "Pandas Dtype": df_docket.dtypes.astype(str),
                "Null Count": null_counts.values,
                "Null %": ((null_counts / len(df_docket)) * 100).round(2).values,
            }
        )
        st.dataframe(schema_df, use_container_width=True)

    with diag_tab3:
        st.write("#### Duplicate comment_id Rows")
        if "comment_id" in df_docket.columns:
            comment_id_counts = df_docket["comment_id"].value_counts()
            duplicate_ids = comment_id_counts[comment_id_counts > 1].index.tolist()
            if duplicate_ids:
                dup_rows = df_docket[
                    df_docket["comment_id"].isin(duplicate_ids)
                ].sort_values("comment_id")
                st.dataframe(dup_rows, use_container_width=True)
            else:
                st.success("No duplicate comment_id rows found.")
        else:
            st.info("comment_id column not available.")

    with diag_tab4:
        st.write("#### Sample Raw Records Expanded as JSON")
        sample_count = min(3, len(df_docket))
        sample_df = df_docket.sample(sample_count, random_state=42)
        for idx, (_, row) in enumerate(sample_df.iterrows(), 1):
            with st.expander(f"Raw Sample #{idx} (Row index {row.name})"):
                row_dict = row.to_dict()
                for k, v in row_dict.items():
                    if isinstance(v, pd.Timestamp):
                        row_dict[k] = str(v)
                    elif pd.isna(v):
                        row_dict[k] = None
                st.json(row_dict)

    with diag_tab5:
        st.write("#### Enriched Comment Attachments Catalog")
        if df_attachments_docket is not None and not df_attachments_docket.empty:
            st.success(
                f"Discovered **{len(df_attachments_docket)}** attachment files for docket `{active_docket}`."
            )

            # Extract statuses safely to support schema variations and avoid drift crashes
            status_col = (
                "download_status"
                if "download_status" in df_attachments_docket.columns
                else None
            )

            pending_count = 0
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            total_size_bytes = 0.0

            if status_col:
                pending_count = int(
                    (df_attachments_docket[status_col] == "pending").sum()
                )
                downloaded_count = int(
                    (df_attachments_docket[status_col] == "downloaded").sum()
                )
                skipped_count = int(
                    (df_attachments_docket[status_col] == "skipped").sum()
                )
                failed_count = int(
                    (df_attachments_docket[status_col] == "failed").sum()
                )
            else:
                pending_count = len(df_attachments_docket)

            if "size_bytes_actual" in df_attachments_docket.columns:
                total_size_bytes = (
                    df_attachments_docket["size_bytes_actual"].dropna().sum()
                )

            total_size_mb = round(total_size_bytes / (1024 * 1024), 2)

            # Render visual telemetry metrics
            st.write("##### Telemetry & Download Metrics")
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("Pending Downloads", pending_count)
            with m2:
                st.metric("Downloaded Files", downloaded_count)
            with m3:
                st.metric("Skipped Files", skipped_count)
            with m4:
                st.metric("Failed Downloads", failed_count)
            with m5:
                st.metric("Total Downloaded Size", f"{total_size_mb} MB")

            st.write("##### Cataloged Attachments Registry")
            table_cols = [
                "attachment_id",
                "comment_id",
                "file_name",
                "format",
                "size_bytes",
            ]
            if status_col:
                table_cols.append("download_status")
            if "local_path" in df_attachments_docket.columns:
                table_cols.append("local_path")
            if "download_error" in df_attachments_docket.columns:
                table_cols.append("download_error")
            if "checksum_sha256" in df_attachments_docket.columns:
                table_cols.append("checksum_sha256")

            table_cols = [c for c in table_cols if c in df_attachments_docket.columns]
            st.dataframe(df_attachments_docket[table_cols], use_container_width=True)
        else:
            st.info(
                "No attachments cataloged for this docket yet. Run ParserAgent v2A to catalog comments."
            )

    # Duplicate text inspection
    st.subheader("Duplicate Text Inspection")
    candidate_text_cols = ["comment_text", "text", "body", "raw_text", "parsed_text"]
    text_col_to_use = None
    for col in candidate_text_cols:
        if col in df_docket.columns:
            text_col_to_use = col
            break

    if text_col_to_use:
        non_empty_texts = df_docket[text_col_to_use].dropna().astype(str).str.strip()
        non_empty_texts = non_empty_texts[non_empty_texts != ""]

        if not non_empty_texts.empty:
            st.write(f"Analyzing duplicate comments in column: `{text_col_to_use}`")
            dup_text_df = get_duplicate_text_stats(df, active_docket, text_col_to_use)
            if not dup_text_df.empty:
                st.dataframe(dup_text_df, use_container_width=True)
            else:
                st.success("No duplicate normalized comments found for this docket ID.")
        else:
            st.warning(
                "Raw comment body not available in bronze; ParserAgent will populate silver parsed text."
            )
    else:
        st.warning(
            "Raw comment body not available in bronze; ParserAgent will populate silver parsed text."
        )

    # Silver Parsed Comments Section
    st.markdown("---")
    st.subheader("Silver Parsed Comments Panel")

    if df_silver is not None and not df_silver.empty:
        if not df_silver_docket.empty:
            total_silver = len(df_silver_docket)
            st.markdown(
                f"Found silver table at `{silver_path}` with **{total_silver}** parsed rows for docket `{active_docket}`."
            )

            # Metrics Row 1
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Total Silver Rows", total_silver)
            with c2:
                if "char_count" in df_silver_docket.columns:
                    avg_char = round(df_silver_docket["char_count"].mean(), 1)
                    st.metric("Average Char Count", avg_char)
                else:
                    st.metric("Average Char Count", "N/A")
            with c3:
                if "parse_status" in df_silver_docket.columns:
                    err_count = (df_silver_docket["parse_status"] == "error").sum()
                    st.metric("Parse Errors", int(err_count))
                else:
                    st.metric("Parse Errors", "N/A")

            # Metrics Row 2 (Enriched statistics)
            c4, c5, c6 = st.columns(3)
            with c4:
                enriched_success = 0
                if df_details_docket is not None and not df_details_docket.empty:
                    if "enrichment_status" in df_details_docket.columns:
                        enriched_success = (
                            df_details_docket["enrichment_status"] == "success"
                        ).sum()
                st.metric("Enriched Comment Details", int(enriched_success))
            with c5:
                num_attachments = 0
                if (
                    df_attachments_docket is not None
                    and not df_attachments_docket.empty
                ):
                    num_attachments = len(df_attachments_docket)
                st.metric("Cataloged Attachments", int(num_attachments))
            with c6:
                num_covers = 0
                if df_details_docket is not None and not df_details_docket.empty:
                    if "is_cover_note" in df_details_docket.columns:
                        num_covers = df_details_docket["is_cover_note"].sum()
                st.metric("Boilerplate Cover Notes", int(num_covers))

            # Breakdowns
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                st.write("#### Parse Status breakdown")
                if "parse_status" in df_silver_docket.columns:
                    status_counts = (
                        df_silver_docket["parse_status"].value_counts().reset_index()
                    )
                    status_counts.columns = ["parse_status", "count"]
                    st.dataframe(status_counts, use_container_width=True)
            with col_b2:
                st.write("#### Text Source breakdown")
                if "text_source" in df_silver_docket.columns:
                    source_counts = (
                        df_silver_docket["text_source"].value_counts().reset_index()
                    )
                    source_counts.columns = ["text_source", "count"]
                    st.dataframe(source_counts, use_container_width=True)

            # Top duplicates
            st.write("#### Top Duplicate Normalized Text Hashes")
            if "normalized_text_hash" in df_silver_docket.columns:
                hash_counts = df_silver_docket["normalized_text_hash"].dropna()
                hash_counts = hash_counts[hash_counts != ""]
                if not hash_counts.empty:
                    dup_hashes = hash_counts.value_counts()
                    dup_hashes = dup_hashes[dup_hashes > 1].reset_index()
                    dup_hashes.columns = ["normalized_text_hash", "count"]
                    if not dup_hashes.empty:
                        hash_to_sample = {}
                        for _, r in df_silver_docket.iterrows():
                            h = r.get("normalized_text_hash")
                            t = r.get("normalized_text") or r.get("raw_text")
                            if h and t and h not in hash_to_sample:
                                hash_to_sample[h] = str(t)
                        dup_hashes["sample_text"] = dup_hashes[
                            "normalized_text_hash"
                        ].map(hash_to_sample)
                        st.dataframe(dup_hashes.head(10), use_container_width=True)
                    else:
                        st.success("No duplicate normalized text hashes found.")
                else:
                    st.info("No normalized text hashes available.")

            # Table preview
            st.write("#### Parsed Comments Preview")
            preview_cols = [
                "comment_id",
                "parse_status",
                "text_source",
                "char_count",
                "has_attachments",
                "attachment_count",
                "normalized_text",
            ]
            preview_cols = [c for c in preview_cols if c in df_silver_docket.columns]
            st.dataframe(
                df_silver_docket[preview_cols].head(row_limit), use_container_width=True
            )
        else:
            st.warning(
                f"Silver table loaded, but no parsed comments found for docket `{active_docket}`."
            )
    else:
        st.info("“Silver table not found yet. Run ParserAgent.”")

    # Silver Embeddings Section
    st.markdown("---")
    st.subheader("Silver Comment Embeddings Panel")

    if df_embeddings is None:
        st.info("Embeddings table not found yet. Run EmbeddingAgent.")
    elif df_embeddings_docket.empty:
        st.warning(
            f"Embeddings table loaded, but no embeddings found for docket `{active_docket}`."
        )
    else:
        st.markdown(
            f"Found embeddings table at `{embeddings_path}` with "
            f"**{len(df_embeddings_docket)}** rows for docket `{active_docket}`."
        )

        e1, e2, e3 = st.columns(3)
        with e1:
            st.metric("Total Embedding Rows", len(df_embeddings_docket))
        with e2:
            dims = unique_values(df_embeddings_docket, "embedding_dim")
            st.metric("Embedding Dim Values", ", ".join(map(str, dims)) or "N/A")
        with e3:
            if "embedded_at" in df_embeddings_docket.columns:
                embedded_at = pd.to_datetime(
                    df_embeddings_docket["embedded_at"], errors="coerce"
                ).dropna()
                if not embedded_at.empty:
                    st.metric(
                        "Embedded At Range",
                        f"{embedded_at.min()} -> {embedded_at.max()}",
                    )
                else:
                    st.metric("Embedded At Range", "N/A")
            else:
                st.metric("Embedded At Range", "N/A")

        if (
            "backend" in df_embeddings_docket.columns
            and (df_embeddings_docket["backend"].astype(str) == "mock").any()
        ):
            st.warning(
                "This docket includes mock embeddings; clustering is not semantic."
            )

        e_tab1, e_tab2, e_tab3 = st.columns(3)
        with e_tab1:
            st.write("#### Count by embedding_model")
            st.dataframe(
                value_counts_df(df_embeddings_docket, "embedding_model"),
                use_container_width=True,
            )
        with e_tab2:
            st.write("#### Count by backend")
            st.dataframe(
                value_counts_df(df_embeddings_docket, "backend"),
                use_container_width=True,
            )
        with e_tab3:
            st.write("#### Count by text_source")
            st.dataframe(
                value_counts_df(df_embeddings_docket, "text_source"),
                use_container_width=True,
            )

        st.write("#### Embeddings Preview")
        embedding_preview_cols = available_columns(
            df_embeddings_docket,
            [
                "comment_id",
                "embedding_model",
                "backend",
                "embedding_dim",
                "text_source",
                "text_hash",
                "embedded_at",
            ],
        )
        st.dataframe(
            df_embeddings_docket[embedding_preview_cols].head(row_limit),
            use_container_width=True,
        )

    # Gold Clusters Section
    st.markdown("---")
    st.subheader("Gold Comment Clusters Panel")

    if (
        df_clusters is None
        or df_memberships is None
        or df_clusters_docket.empty
        or df_memberships_docket.empty
    ):
        st.info("Gold cluster tables not found yet. Run ClusteringAgent.")
        return

    st.markdown(
        f"Found gold cluster tables with **{len(df_clusters_docket)}** clusters and "
        f"**{len(df_memberships_docket)}** memberships for docket `{active_docket}`."
    )

    cluster_filter_df = df_clusters_docket.copy()
    membership_filter_df = df_memberships_docket.copy()

    model_options = unique_values(cluster_filter_df, "embedding_model")
    if model_options:
        selected_model = st.selectbox("Filter embedding_model", options=model_options)
        cluster_filter_df = cluster_filter_df[
            cluster_filter_df["embedding_model"] == selected_model
        ]
        membership_filter_df = membership_filter_df[
            membership_filter_df["embedding_model"] == selected_model
        ]

    threshold_options = unique_values(cluster_filter_df, "similarity_threshold")
    if threshold_options:
        selected_threshold = st.selectbox(
            "Filter similarity_threshold", options=threshold_options
        )
        cluster_filter_df = cluster_filter_df[
            cluster_filter_df["similarity_threshold"] == selected_threshold
        ]
        membership_filter_df = membership_filter_df[
            membership_filter_df["similarity_threshold"] == selected_threshold
        ]

    run_id_options = unique_values(cluster_filter_df, "clustering_run_id")
    if len(run_id_options) > 1:
        selected_run_id = st.selectbox(
            "Filter clustering_run_id", options=run_id_options
        )
        cluster_filter_df = cluster_filter_df[
            cluster_filter_df["clustering_run_id"] == selected_run_id
        ]
        membership_filter_df = membership_filter_df[
            membership_filter_df["clustering_run_id"] == selected_run_id
        ]

    if cluster_filter_df.empty or membership_filter_df.empty:
        st.info("No clusters match the selected filters.")
        return

    # Compute baseline exact-hash statistics
    baseline_stats = get_exact_hash_baseline_stats(df_silver_docket, active_docket)
    sub_rows = baseline_stats["substantive_rows"]
    largest_embedding_cluster_size = (
        int(cluster_filter_df["cluster_size"].max())
        if not cluster_filter_df.empty and "cluster_size" in cluster_filter_df.columns
        else 0
    )
    total_membership_uniq = (
        membership_filter_df["comment_id"].nunique()
        if not membership_filter_df.empty
        else 0
    )
    embedding_coverage_pct = (
        round((total_membership_uniq / sub_rows) * 100, 2) if sub_rows > 0 else 0.0
    )

    st.write("### Overall Baseline & Cluster Comparison")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Exact-Hash Baseline (String Match)**")
        st.metric("Substantive Inline Comments", sub_rows)
        st.metric(
            "Exact Duplicate Hash Groups", baseline_stats["duplicate_hash_groups"]
        )
        st.metric(
            "Exact Duplicate Comments Covered",
            baseline_stats["exact_duplicate_comments_covered"],
        )
        st.metric(
            "Largest Exact Duplicate Group",
            baseline_stats["largest_exact_duplicate_group"],
        )
        st.metric(
            "Exact Duplicate Coverage Pct",
            f"{baseline_stats['exact_duplicate_coverage_pct']}%",
        )

    with col_right:
        st.markdown("**Semantic Clustering (Embedding-Based)**")
        st.metric("Total Clusters", len(cluster_filter_df))
        st.metric("Total Memberships", len(membership_filter_df))
        st.metric("Largest Embedding Cluster Size", largest_embedding_cluster_size)
        st.metric("Embedding Cluster Coverage Pct", f"{embedding_coverage_pct}%")

    st.info(
        f"**Methodological Insight:** "
        f"Exact-string matching detects only {baseline_stats['exact_duplicate_comments_covered']} comments ({baseline_stats['exact_duplicate_coverage_pct']}%) "
        f"as duplicates. In contrast, embedding-based clustering with a "
        f"{selected_threshold if 'selected_threshold' in locals() else 'similarity'} threshold "
        f"identifies {total_membership_uniq} comments ({embedding_coverage_pct}%) in coordinated campaigns. "
        f"This demonstrates that paraphrasing, minor structural alterations, and personalized templates account for the vast majority "
        f"of coordinated public comment campaigns, which simple exact-hash baseline systems miss."
    )

    st.write("#### Cluster Run Values")
    run_values = {
        "embedding_model": ", ".join(
            map(str, unique_values(cluster_filter_df, "embedding_model"))
        )
        or "N/A",
        "clustering_version": ", ".join(
            map(str, unique_values(cluster_filter_df, "clustering_version"))
        )
        or "N/A",
        "clustering_run_id": ", ".join(
            map(str, unique_values(cluster_filter_df, "clustering_run_id"))
        )
        or "N/A",
    }
    st.json(run_values)

    if (
        "embedding_backend" in cluster_filter_df.columns
        and (cluster_filter_df["embedding_backend"].astype(str) == "mock").any()
    ):
        st.warning(
            "Source embedding backend is mock; clusters are for plumbing/debug only."
        )

    st.write("#### Cluster Table")
    cluster_cols = available_columns(
        cluster_filter_df,
        [
            "cluster_id",
            "cluster_size",
            "representative_comment_id",
            "representative_text_hash",
            "mean_similarity",
            "min_similarity",
            "max_similarity",
            "candidate_count",
            "embedding_backend",
            "created_at",
            "clustered_at",
            "updated_at",
        ],
    )
    cluster_table = cluster_filter_df[cluster_cols].sort_values(
        by="cluster_size" if "cluster_size" in cluster_cols else "cluster_id",
        ascending=False,
    )
    st.dataframe(cluster_table.head(row_limit), use_container_width=True)

    cluster_ids = cluster_table["cluster_id"].dropna().astype(str).tolist()
    selected_cluster_id = st.selectbox("Select Cluster ID", options=cluster_ids)

    selected_members = membership_filter_df[
        membership_filter_df["cluster_id"].astype(str) == selected_cluster_id
    ].copy()
    if "membership_rank" in selected_members.columns:
        selected_members = selected_members.sort_values("membership_rank")

    # Get selected cluster info
    cluster_info = cluster_table[
        cluster_table["cluster_id"].astype(str) == selected_cluster_id
    ].iloc[0]

    # Calculate cluster metrics
    cluster_size = len(selected_members)
    unique_hash_count = (
        selected_members["text_hash"].nunique()
        if "text_hash" in selected_members.columns
        else 0
    )

    cluster_hashes = (
        selected_members["text_hash"].dropna()
        if "text_hash" in selected_members.columns
        else pd.Series(dtype=str)
    )
    cluster_hash_counts = cluster_hashes.value_counts()
    cluster_dup_hashes = cluster_hash_counts[cluster_hash_counts > 1]
    exact_dup_groups_in_cluster = len(cluster_dup_hashes)
    exact_dup_members_in_cluster = int(cluster_dup_hashes.sum())
    max_group_size = (
        int(cluster_hash_counts.max()) if not cluster_hash_counts.empty else 0
    )

    # Determine campaign style label
    if cluster_size <= 1:
        cluster_label = "Single-member / Inconclusive"
        label_desc = "This cluster is too small to determine a campaign style."
    elif unique_hash_count >= cluster_size * 0.8:
        cluster_label = "Embedding/paraphrase-driven"
        label_desc = "Almost all members in this cluster have unique text hashes, indicating a sophisticated paraphrase or template-modification campaign."
    elif max_group_size >= cluster_size * 0.6:
        cluster_label = "Exact-duplicate-driven"
        label_desc = "The vast majority of comments in this cluster share a single identical text hash, indicating a simple copy-paste campaign."
    else:
        cluster_label = "Mixed"
        label_desc = "This cluster contains a mix of exact copy-pastes and paraphrased/modified template variations."

    st.markdown("### Selected Cluster Evidence Summary")

    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        st.metric("Cluster Size", cluster_size)
    with mc2:
        st.metric("Unique Text Hashes", unique_hash_count)
    with mc3:
        st.metric("Exact Duplicate Groups", exact_dup_groups_in_cluster)
        st.metric("Exact Duplicate Members", exact_dup_members_in_cluster)
    with mc4:
        st.metric("Campaign Style", cluster_label)

    st.info(f"**Campaign Style Details:** {label_desc}")

    # Representative comment info
    rep_id = cluster_info.get("representative_comment_id", "N/A")
    st.markdown(f"**Representative Comment ID:** `{rep_id}`")

    rep_text = "N/A"
    if df_silver_docket is not None and not df_silver_docket.empty:
        rep_row = df_silver_docket[df_silver_docket["comment_id"] == rep_id]
        if not rep_row.empty:
            rep_text = (
                rep_row["raw_text"].iloc[0]
                or rep_row["normalized_text"].iloc[0]
                or "N/A"
            )

    st.text_area(
        "Representative Text Preview", value=rep_text, height=150, disabled=True
    )

    # Selected Cluster Member Table
    st.write("#### Selected Cluster Members")

    if df_silver_docket is not None and not df_silver_docket.empty:
        joined_members = selected_members.merge(
            df_silver_docket[
                [
                    "comment_id",
                    "title",
                    "posted_date",
                    "last_modified_date",
                    "raw_text",
                    "normalized_text",
                    "normalized_text_hash",
                ]
            ],
            on="comment_id",
            how="left",
        )
    else:
        joined_members = selected_members.copy()
        joined_members["title"] = "N/A"
        joined_members["posted_date"] = "N/A"
        joined_members["last_modified_date"] = "N/A"
        joined_members["raw_text"] = "N/A"
        joined_members["normalized_text"] = "N/A"
        joined_members["normalized_text_hash"] = (
            joined_members["text_hash"]
            if "text_hash" in joined_members.columns
            else "N/A"
        )

    # Rename text_hash to normalized_text_hash if needed
    if (
        "normalized_text_hash" not in joined_members.columns
        and "text_hash" in joined_members.columns
    ):
        joined_members["normalized_text_hash"] = joined_members["text_hash"]

    # Generate text_preview
    joined_members["text_preview"] = ""
    if "raw_text" in joined_members.columns:
        joined_members["text_preview"] = joined_members["text_preview"].mask(
            joined_members["text_preview"].astype(str).str.strip() == "",
            joined_members["raw_text"],
        )
    if "normalized_text" in joined_members.columns:
        joined_members["text_preview"] = joined_members["text_preview"].mask(
            joined_members["text_preview"].astype(str).str.strip() == "",
            joined_members["normalized_text"],
        )
    joined_members["text_preview"] = (
        joined_members["text_preview"].fillna("").astype(str).str.slice(0, 300)
    )

    member_table_cols = [
        "comment_id",
        "membership_rank",
        "similarity_to_representative",
        "normalized_text_hash",
        "title",
        "posted_date",
        "last_modified_date",
        "text_preview",
    ]
    member_table_cols = [c for c in member_table_cols if c in joined_members.columns]
    st.dataframe(
        joined_members[member_table_cols].head(row_limit), use_container_width=True
    )


if __name__ == "__main__":
    run_app()
