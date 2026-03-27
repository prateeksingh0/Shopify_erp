from django.urls import path
from syncing.views import SyncView

urlpatterns = [
    path('<str:store_name>/sync/', SyncView.as_view(), name='sync'),
]