from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0003_camera_tenant_gateway_tenant"),
    ]

    operations = [
        migrations.AlterField(
            model_name="camera",
            name="connection_mode",
            field=models.CharField(
                choices=[
                    ("direct_rtsp", "Direct RTSP"),
                    ("rtmp_push", "RTMP Push"),
                    ("push", "Push"),
                    ("gateway", "Gateway"),
                ],
                default="direct_rtsp",
                max_length=32,
            ),
        ),
    ]
