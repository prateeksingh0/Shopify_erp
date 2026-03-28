from django.urls import path
from .views import StoreListView, StoreDetailView, StoreClearDataView

urlpatterns = [
    path('', StoreListView.as_view()),
    path('<str:store_name>/', StoreDetailView.as_view()),
    path('<str:store_name>/clear-data/', StoreClearDataView.as_view()),
]