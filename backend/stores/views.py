import os
import shutil


from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Store
from .serializers import StoreSerializer, StoreConnectSerializer
from .token_manager import generate_access_token

def get_store_or_404(store_name, user):
    try:
        return Store.objects.get(store_name=store_name, user=user)
    except Store.DoesNotExist:
        return None


def get_store_base(user_id, store_name):
    base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
    return os.path.join(base, str(user_id), store_name)


class StoreListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stores = Store.objects.filter(user=request.user).values(
            'store_name', 'domain', 'created_at'
        )
        return Response(list(stores))

    def post(self, request):
        serializer = StoreConnectSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        domain        = serializer.validated_data['domain'].strip().lower()
        client_id     = serializer.validated_data['client_id'].strip()
        client_secret = serializer.validated_data['client_secret'].strip()

        if not domain.endswith('.myshopify.com'):
            return Response(
                {'error': 'Domain must end with .myshopify.com'},
                status=400
            )

        store_name = domain.split('.')[0]

        # Generate access token via client credentials
        try:
            access_token = generate_access_token(domain, client_id, client_secret)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

        # Save or update store
        store, created = Store.objects.update_or_create(
            store_name=store_name,
            user=request.user,
            defaults={
                'domain':        domain,
                'client_id':     client_id,
                'client_secret': client_secret,
                'access_token':  access_token,
            }
        )

        return Response(
            StoreSerializer(store).data,
            status=201 if created else 200
        )


class StoreDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        try:
            store = Store.objects.get(store_name=store_name, user=request.user)
            return Response(StoreSerializer(store).data)
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=404)

    def delete(self, request, store_name):
        try:
            store = Store.objects.get(store_name=store_name, user=request.user)
            store.delete()
            return Response({'message': f'Store {store_name} deleted'})
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=404)
        

class StoreClearDataView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        store_dir = os.path.join(get_store_base(request.user.id, store_name))

        if not os.path.exists(store_dir):
            return Response({'error': 'No data found for this store'}, status=404)

        try:
            shutil.rmtree(store_dir)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

        return Response({'message': f'Data cleared for store {store_name}'})