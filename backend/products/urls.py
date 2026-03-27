from django.urls import path
from .views import (
    FetchProductsView,
    ProductsView,
    LocationsView,
    CollectionHandlesView,
    MetafieldDefsView,
    MetafieldOwnersView,
    FieldSchemaView,
    SaveProductsView,
)

urlpatterns = [
    path('<str:store_name>/fetch/', FetchProductsView.as_view()),
    path('<str:store_name>/products/', ProductsView.as_view()),
    path('<str:store_name>/locations/', LocationsView.as_view()),
    path('<str:store_name>/save/', SaveProductsView.as_view()),
    path('<str:store_name>/collection-handles/', CollectionHandlesView.as_view()),
    path('<str:store_name>/metafield-defs/', MetafieldDefsView.as_view()),
    path('<str:store_name>/metafield-owners/', MetafieldOwnersView.as_view()),
    path('<str:store_name>/field-schema/', FieldSchemaView.as_view()),
]