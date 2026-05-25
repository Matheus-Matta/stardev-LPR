from tenants.utils import (
    business_admin_profile,
    business_ids_administered_by,
    business_ids_visible_for_user,
    tenants_visible_for_user,
)


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.business = None
        request.business_admin_profile = None
        request.administered_businesses = []
        request.visible_businesses = []
        request.tenant = None
        request.visible_tenants = []
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            profile = business_admin_profile(user)
            request.business_admin_profile = profile
            request.administered_businesses = list(business_ids_administered_by(user))
            request.visible_businesses = list(business_ids_visible_for_user(user))
            request.visible_tenants = list(tenants_visible_for_user(user))
            if profile:
                request.business = profile.business
            tenant_id = request.headers.get("X-Tenant-ID") or request.GET.get("tenant_id")
            tenants = tenants_visible_for_user(user)
            if tenant_id:
                request.tenant = tenants.filter(id=tenant_id).first()
            else:
                request.tenant = tenants.first()
            if request.tenant and not request.business:
                request.business = request.tenant.business
        return self.get_response(request)
