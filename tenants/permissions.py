from rest_framework import permissions

from tenants.utils import business_ids_administered_by


class IsBusinessAdminOrSystemAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return business_ids_administered_by(user).exists()
