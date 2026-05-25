from rest_framework.throttling import UserRateThrottle


class UploadBurstRateThrottle(UserRateThrottle):
    scope = "upload_burst"

