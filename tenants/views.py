from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import Business, Tenant, UserTenantAccess
from tenants.permissions import IsBusinessAdminOrSystemAdmin
from tenants.serializers import (
    BusinessSerializer,
    GrantTenantAccessSerializer,
    ManagedTenantAccessSerializer,
    TenantSerializer,
    UserTenantAccessSerializer,
)
from tenants.utils import business_ids_administered_by, tenants_visible_for_user


class BusinessListCreateAPIView(generics.ListCreateAPIView):
    queryset = Business.objects.all()
    serializer_class = BusinessSerializer
    permission_classes = [permissions.IsAdminUser]


class BusinessDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Business.objects.all()
    serializer_class = BusinessSerializer
    permission_classes = [permissions.IsAdminUser]


class TenantListCreateAPIView(generics.ListCreateAPIView):
    queryset = Tenant.objects.select_related("business")
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAdminUser]


class TenantDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Tenant.objects.select_related("business")
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAdminUser]


class UserTenantAccessListCreateAPIView(generics.ListCreateAPIView):
    queryset = UserTenantAccess.objects.select_related("user", "business", "tenant")
    serializer_class = UserTenantAccessSerializer
    permission_classes = [permissions.IsAdminUser]


class UserTenantAccessDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = UserTenantAccess.objects.select_related("user", "business", "tenant")
    serializer_class = UserTenantAccessSerializer
    permission_classes = [permissions.IsAdminUser]


class MyBusinessListAPIView(generics.ListAPIView):
    serializer_class = BusinessSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return business_ids_administered_by(self.request.user)


class MyTenantListAPIView(generics.ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return tenants_visible_for_user(self.request.user).distinct()


class ManagedTenantAccessListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ManagedTenantAccessSerializer
    permission_classes = [IsBusinessAdminOrSystemAdmin]

    def get_queryset(self):
        businesses = business_ids_administered_by(self.request.user)
        return UserTenantAccess.objects.select_related("user", "business", "tenant").filter(
            business__in=businesses
        )


class ManagedTenantAccessDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ManagedTenantAccessSerializer
    permission_classes = [IsBusinessAdminOrSystemAdmin]

    def get_queryset(self):
        businesses = business_ids_administered_by(self.request.user)
        return UserTenantAccess.objects.select_related("user", "business", "tenant").filter(
            business__in=businesses
        )


class GrantTenantAccessAPIView(APIView):
    permission_classes = [IsBusinessAdminOrSystemAdmin]

    def post(self, request):
        serializer = GrantTenantAccessSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        access = serializer.save()
        return Response(serializer.to_representation(access), status=201)
