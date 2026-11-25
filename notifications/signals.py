import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from tasks.models import Task

from .models import EmailNotification
from .services import deliver_notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Task, dispatch_uid="notifications.task_created")
def notify_new_task(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        notification, was_created = EmailNotification.objects.get_or_create(
            notification_type=EmailNotification.Type.TASK_CREATED,
            task=instance,
        )
    except Exception:
        logger.exception("Could not record the new-task email for task %s.", instance.pk)
        raise
    if was_created:
        transaction.on_commit(partial(deliver_notification, notification.pk), robust=True)
