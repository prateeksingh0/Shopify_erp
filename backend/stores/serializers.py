from rest_framework import serializers
from .models import Store


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['store_name', 'domain', 'client_id', 'created_at']
        # client_secret and access_token never returned to frontend


class StoreConnectSerializer(serializers.Serializer):
    domain        = serializers.CharField()
    client_id     = serializers.CharField()
    client_secret = serializers.CharField()