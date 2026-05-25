from django.conf import settings


def test_debug_mode_uses_sqlite_and_inline_celery_without_redis():
    if settings.CELERY_DEV_EAGER:
        assert not settings.USE_POSTGRES_IN_DEBUG
        assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
        assert settings.CELERY_TASK_ALWAYS_EAGER
        assert settings.CELERY_BROKER_URL == "memory://"
        assert settings.CELERY_RESULT_BACKEND == "cache+memory://"
        assert (
            settings.CACHES["default"]["BACKEND"]
            == "django.core.cache.backends.locmem.LocMemCache"
        )
    else:
        assert settings.CELERY_BROKER_URL == settings.REDIS_URL
