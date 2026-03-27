import pandas as pd
import os
import products.store_paths as store_paths


def save_csv(rows):

    if not rows:
        print("[CSV] No rows to write.")
        return

    print("[CSV] Generating DataFrame...")

    df = pd.DataFrame(rows)

    # Ensure Delete column always exists (blank by default — user fills in YES to delete)
    if "Delete" not in df.columns:
        df["Delete"] = ""

    # Ensure stable column order
    # Core columns first
    core_columns = [
        "Product ID",
        "Variant ID",
        "Handle",
        "Title",
        "Body (HTML)",
        "Vendor",
        "Type",
        "Tags",
        "Status",
        "Product Category ID",
        "Product Category Name",
        "Product Category Full Path",
        "Created At",
        "Updated At",
        "SEO Title",
        "SEO Description",
        "Option1 Name",
        "Option1 Value",
        "Option2 Name",
        "Option2 Value",
        "Option3 Name",
        "Option3 Value",
        "Variant SKU",
        "Variant Price",
        "Variant Compare At Price",
        "Variant Barcode",
        "Variant Tax Code",
        "Variant Inventory Policy",
        "Inventory Item ID",
        "Cost per item",
        "Variant Grams",
        "Variant Weight Unit",
        "Image URLs",
        "Image Alt Text",
        "Last Synced",
        "Delete",
        "Sync Status"
    ]

    # Dynamic columns
    all_columns = list(df.columns)

    dynamic_columns = [
        c for c in all_columns if c not in core_columns
    ]

    ordered_columns = [
        c for c in core_columns if c in all_columns
    ] + dynamic_columns

    df = df[ordered_columns]

    csv_path = os.path.join(store_paths.DATA_DIR, "products_master.csv")

    print("[CSV] Columns detected:", len(df.columns))
    print("[CSV] Rows written:", len(df))

    df.to_csv(csv_path, index=False)

    print("[CSV] CSV generated:", csv_path)