from django.db import models
from stores.models import Store


class SyncLog(models.Model):
    LOG_TYPE_CHOICES = [
        ('sync',  'Sync'),
        ('fetch', 'Fetch'),
    ]

    store            = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='sync_logs')
    log_type         = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES, default='sync')
    started_at       = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.IntegerField(default=0)
    total            = models.IntegerField(default=0)
    updated          = models.IntegerField(default=0)
    created          = models.IntegerField(default=0)
    skipped          = models.IntegerField(default=0)
    deleted          = models.IntegerField(default=0)
    errors           = models.IntegerField(default=0)
    conflicts        = models.IntegerField(default=0)
    status           = models.CharField(max_length=20, default='success')

    class Meta:
        db_table = 'sync_logs'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.store_id} — {self.log_type} — {self.started_at}"