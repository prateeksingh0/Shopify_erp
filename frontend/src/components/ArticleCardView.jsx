import { memo } from 'react'
import styles from './ArticleCardView.module.css'

const STATUS_DOT = {
    published: '#10b981',
    draft: '#f59e0b',
}

const ArticleCard = memo(function ArticleCard({ row, onClick }) {
    const status = String(row['Status'] || '').toLowerCase()
    const dotColor = STATUS_DOT[status] || '#94a3b8'
    const imgUrl = String(row['Image URL'] || '')

    return (
        <div className={styles.card} onClick={onClick}>
            <div className={styles.cardImg}>
                {imgUrl
                    ? <img src={imgUrl} alt={row['Image Alt'] || ''} loading="lazy" decoding="async" className={styles.cardImgEl} />
                    : <span className={styles.noImg}>No image</span>
                }
            </div>
            <div className={styles.cardBody}>
                <div className={styles.cardMeta}>
                    <span className={styles.statusDot} style={{ background: dotColor }} />
                    <span className={styles.blogName}>{row['Blog Title'] || '—'}</span>
                </div>
                <div className={styles.cardTitle}>{row['Title'] || '—'}</div>
                <div className={styles.cardAuthor}>{row['Author'] || ''}</div>
                {row['Tags'] && <div className={styles.cardTags}>{row['Tags']}</div>}
                <div className={styles.cardDate}>
                    {row['Published At'] ? new Date(row['Published At']).toLocaleDateString() : 'Draft'}
                </div>
            </div>
        </div>
    )
})

export default function ArticleCardView({ rows, onCardClick }) {
    if (!rows.length) return (
        <div className={styles.empty}>No articles to display</div>
    )
    return (
        <div className={styles.grid}>
            {rows.map((row, i) => (
                <ArticleCard
                    key={row['Article ID'] || i}
                    row={row}
                    onClick={() => onCardClick(row)}
                />
            ))}
        </div>
    )
}
