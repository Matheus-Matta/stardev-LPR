from rest_framework.throttling import SimpleRateThrottle


class SafeSimpleRateThrottle(SimpleRateThrottle):
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            return True


class CameraIngestRateThrottle(SafeSimpleRateThrottle):
    scope = "camera_ingest"

    def get_cache_key(self, request, view):
        camera_key = view.kwargs.get("camera_key", "")
        if not camera_key:
            return None
        return self.cache_format % {"scope": self.scope, "ident": camera_key}


class GatewayIngestRateThrottle(SafeSimpleRateThrottle):
    scope = "gateway_ingest"

    def get_cache_key(self, request, view):
        gateway_key = view.kwargs.get("gateway_key", "")
        if not gateway_key:
            return None
        return self.cache_format % {"scope": self.scope, "ident": gateway_key}
