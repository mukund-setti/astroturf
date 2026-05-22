#!/usr/bin/env python3
"""inspect_docket.py — Inspect a local Delta table using deltalake and pandas."""

import argparse
import hashlib
import os
import re

from deltalake import DeltaTable


def main():
    parser = argparse.ArgumentParser(
        description="Inspect a local Delta table for a given docket."
    )
    parser.add_argument(
        "--docket",
        required=True,
        help="Regulations.gov Docket ID (e.g. FDA-2013-S-0610)",
    )
    parser.add_argument(
        "--bronze-path",
        default="./data/bronze/raw_comments",
        help="Path to local Delta table",
    )

    args = parser.parse_args()

    # Check if the Delta table exists
    if not os.path.exists(args.bronze_path) or not DeltaTable.is_deltatable(
        args.bronze_path
    ):
        print(
            f"ERROR: No Delta table found at '{args.bronze_path}'. Please run ingestion first."
        )
        return

    try:
        dt = DeltaTable(args.bronze_path)
        df = dt.to_pandas()
    except Exception as e:
        print(f"ERROR: Could not load Delta table or convert to pandas: {e}")
        return

    # Filter records by docket
    if "docket_id" in df.columns:
        df_docket = df[df["docket_id"] == args.docket]
    else:
        print("WARNING: 'docket_id' column not present in the Delta table columns.")
        df_docket = df

    total_rows = len(df_docket)

    print("=" * 70)
    print("DELTA TABLE DOCKET INSPECTION REPORT")
    print(f"Docket ID:      {args.docket}")
    print(f"Bronze Path:    {args.bronze_path}")
    print("=" * 70)
    print(f"Total rows for docket: {total_rows}")

    if total_rows == 0:
        print("No records found for this docket.")
        return

    # Unique comment_id count
    if "comment_id" in df_docket.columns:
        unique_comments = df_docket["comment_id"].nunique()
        print(f"Unique comment_id count: {unique_comments}")
    else:
        print("Unique comment_id count: not available")

    # Min/max received_date or last_modified_date
    for col in ["received_date", "last_modified_date", "posted_date"]:
        if col in df_docket.columns:
            series = df_docket[col].dropna()
            if not series.empty:
                print(f"{col} range: {series.min()} to {series.max()}")
            else:
                print(f"{col} range: not available (all null)")
        else:
            print(f"{col} range: not available")

    # Null/empty comment text count
    if "comment_text" in df_docket.columns:
        comment_text_col = df_docket["comment_text"]
        null_count = comment_text_col.isna().sum()
        empty_count = (comment_text_col.astype(str).str.strip() == "").sum()
        print(
            f"Null/empty comment text count: {null_count + empty_count} (Null: {null_count}, Empty: {empty_count})"
        )
    else:
        print("Null/empty comment text count: not available")

    # Attachment count
    if "has_attachments" in df_docket.columns:
        # Check sum if boolean/numeric
        attachment_count = df_docket["has_attachments"].sum()
        print(f"Attachment count (has_attachments=True): {attachment_count}")
    else:
        print("Attachment count: not available")

    # Top 10 duplicate normalized text hashes
    if "comment_text" in df_docket.columns:
        texts = df_docket["comment_text"].dropna().astype(str).str.strip()
        texts = texts[texts != ""]
        if not texts.empty:
            # Normalize: lowercase, strip, collapse all whitespace to single space
            normalized = texts.apply(lambda x: re.sub(r"\s+", " ", x.lower().strip()))
            hashes = normalized.apply(
                lambda x: hashlib.sha256(x.encode("utf-8")).hexdigest()
            )
            hash_counts = hashes.value_counts()
            duplicates = hash_counts[hash_counts > 1]
            if not duplicates.empty:
                print(
                    "\nTop 10 exact duplicate normalized text hashes (casing/whitespace collapsed):"
                )
                for h, count in duplicates.head(10).items():
                    sample_text = texts[hashes == h].iloc[0]
                    preview = (
                        (sample_text[:60] + "...")
                        if len(sample_text) > 60
                        else sample_text
                    )
                    preview = preview.replace("\n", " ").replace("\r", " ")
                    print(
                        f'  - {h[:12]}... : {count} occurrences | Sample: "{preview}"'
                    )
            else:
                print(
                    "\nTop 10 exact duplicate normalized text hashes: no duplicates found"
                )
        else:
            print(
                "\nTop 10 exact duplicate normalized text hashes: not available (all text is null/empty)"
            )
    else:
        print("\nTop 10 exact duplicate normalized text hashes: not available")

    # Sample 3 records
    print("\nSample 3 records:")
    sample_size = min(3, total_rows)
    # pandas sample can throw an error if sample_size is 0, but total_rows > 0 is checked above
    df_sample = df_docket.sample(sample_size, random_state=42)
    for idx, (_, row) in enumerate(df_sample.iterrows(), 1):
        print(f"\nSample #{idx}:")
        cid = row.get("comment_id", "not available")
        title = row.get("title", "not available")
        received = row.get("received_date", "not available")
        posted = row.get("posted_date", "not available")
        text = row.get("comment_text", None)

        print(f"  Comment ID:    {cid}")
        print(f"  Title:         {title}")
        print(f"  Received Date: {received}")
        print(f"  Posted Date:   {posted}")

        if text is not None:
            text_str = str(text).strip()
            if text_str:
                preview = (text_str[:150] + "...") if len(text_str) > 150 else text_str
                preview = preview.replace("\n", " ").replace("\r", " ")
                print(f'  Text Preview:  "{preview}"')
            else:
                print("  Text Preview:  (empty text)")
        else:
            print("  Text Preview:  not available")
    print("=" * 70)


if __name__ == "__main__":
    main()
