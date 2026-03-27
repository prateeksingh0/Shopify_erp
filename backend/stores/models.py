from django.db import models


class Store(models.Model):
    store_name    = models.CharField(max_length=100, primary_key=True)
    domain        = models.CharField(max_length=255, unique=True)
    client_id     = models.CharField(max_length=255)
    client_secret = models.CharField(max_length=255)
    access_token  = models.CharField(max_length=255, blank=True)
    scopes        = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stores'

    def __str__(self):
        return self.store_name