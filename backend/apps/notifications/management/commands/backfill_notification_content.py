from django.core.management.base import BaseCommand

from apps.notifications.services import backfill_notification_content


class Command(BaseCommand):
    help = "补全已有实验和选课通知的空泛正文，保留已读状态。"

    def handle(self, *args: object, **options: object) -> None:
        count = backfill_notification_content()
        self.stdout.write(self.style.SUCCESS(f"已补全 {count} 条通知正文。"))
