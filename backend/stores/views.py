import requests
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .models import Store
from .serializers import StoreSerializer, StoreConnectSerializer
from .token_manager import generate_access_token


class StoreListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        stores = Store.objects.all().values(
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
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        try:
            store = Store.objects.get(store_name=store_name)
            return Response(StoreSerializer(store).data)
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=404)