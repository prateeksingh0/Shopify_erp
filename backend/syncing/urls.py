from django.urls import path
from syncing.views import SyncView, SyncProductView

urlpatterns = [
    path('<str:store_name>/sync/', SyncView.as_view(), name='sync'),
    path('<str:store_name>/sync/product/<path:product_id>/', SyncProductView.as_view(), name='sync_product'),
]