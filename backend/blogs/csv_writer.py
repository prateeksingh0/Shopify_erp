import os
import pandas as pd
import products.store_paths as store_paths


def save_articles_csv(rows):
    if not rows:
        print("[BLOGS CSV] No rows to write.")
        return

    df = pd.DataFrame(rows)

    core_columns = [
        'Article ID',
        'Blog ID',
        'Blog Title',
        'Blog Handle',
        'Title',
        'Handle',
        'Body (HTML)',
        'Summary (HTML)',
        'Author',
        'Tags',
        'Status',
        'Published At',
        'Created At',
        'Updated At',
        'SEO Title',
        'SEO Description',
        'Image URL',
        'Image Alt',
        'Delete',
        'Sync Status',
    ]

    all_columns     = list(df.columns)
    dynamic_columns = [c for c in all_columns if c not in core_columns]
    ordered_columns = [c for c in core_columns if c in all_columns] + dynamic_columns

    df = df[ordered_columns]

    csv_path = os.path.join(store_paths.DATA_DIR, 'articles_master.csv')
    df.to_csv(csv_path, index=False)

    print(f"[BLOGS CSV] {len(df)} articles written to {csv_path}")