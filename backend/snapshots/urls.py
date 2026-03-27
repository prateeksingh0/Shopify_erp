from django.urls import path
from snapshots.views import SnapshotListView, SnapshotDetailView, SnapshotRollbackView

urlpatterns = [
    path('<str:store_name>/snapshots/', SnapshotListView.as_view(), name='snapshot_list'),
    path('<str:store_name>/snapshots/<str:timestamp>/', SnapshotDetailView.as_view(), name='snapshot_detail'),
    path('<str:store_name>/snapshots/<str:timestamp>/rollback/', SnapshotRollbackView.as_view(), name='snapshot_rollback'),
]