from django.urls import path
from blogs.views import (
    FetchArticlesView,
    ArticlesView,
    SaveArticlesView,
    SyncArticlesView,
    BlogListView,
    BlogMetafieldDefsView,
    CreateBlogView,
    ArticleMetafieldDefsView,
)

urlpatterns = [
    path('<str:store_name>/blogs/fetch/',              FetchArticlesView.as_view(),       name='fetch_articles'),
    path('<str:store_name>/blogs/',                    ArticlesView.as_view(),            name='articles'),
    path('<str:store_name>/blogs/save/',               SaveArticlesView.as_view(),        name='save_articles'),
    path('<str:store_name>/blogs/sync/',               SyncArticlesView.as_view(),        name='sync_articles'),
    path('<str:store_name>/blog-list/',                BlogListView.as_view(),            name='blog_list'),
    path('<str:store_name>/blog-metafield-defs/',      BlogMetafieldDefsView.as_view(),   name='blog_metafield_defs'),
    path('<str:store_name>/blogs/create-blog/',        CreateBlogView.as_view(),          name='create_blog'),
    path('<str:store_name>/article-metafield-defs/',   ArticleMetafieldDefsView.as_view(), name='article_metafield_defs'),
]