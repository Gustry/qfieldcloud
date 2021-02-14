from django.contrib.auth import get_user_model
from django.urls.conf import include
from django.utils.decorators import method_decorator
from django.core.exceptions import ObjectDoesNotExist

from rest_framework import generics, status, permissions
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core.models import (
    Project,
    Organization)
from qfieldcloud.core.serializers import (
    CompleteUserSerializer,
    PublicInfoUserSerializer,
    OrganizationSerializer)
from qfieldcloud.core import permissions_utils, querysets_utils

User = get_user_model()


class ListUsersViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        return permissions_utils.can_list_users_organizations(request.user)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List all users and organizations",
        operation_id="List users and organizations",))
class ListUsersView(generics.ListAPIView):

    serializer_class = PublicInfoUserSerializer
    permission_classes = [permissions.IsAuthenticated,
                          ListUsersViewPermissions]
    paginate_by = 100

    def get_queryset(self):
        params = self.request.GET
        query = params.get('q', '')

        project = None
        if params.get('project'):
            try:
                project = Project.objects.get(id=params.get('project'))
            except Project.DoesNotExist:
                pass

        organization = None
        if params.get('organization'):
            try:
                organization = Organization.objects.get(username=params.get('organization'))
            except Project.DoesNotExist:
                pass

        exclude_organizations = bool(int(params.get('exclude_organizations', 0)))
        return querysets_utils.get_users(
            query,
            project=project,
            organization=organization,
            exclude_organizations=exclude_organizations
        )

class RetrieveUpdateUserViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):

        username = permissions_utils.get_param_from_request(
            request, 'username')

        try:
            user = User.objects.get(username=username)
        except ObjectDoesNotExist:
            return False

        if request.method == 'GET':
            # The queryset is already filtered by what the user can see
            return True
        if request.method in ['PUT', 'PATCH']:
            return permissions_utils.can_update_user(request.user, user)
        return False


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="""Get a single user's (or organization) publicly
        information or complete info if the request is done by the user
        himself""",
        operation_id="Get user",))
@method_decorator(
    name='put', decorator=swagger_auto_schema(
        operation_description="Update a user",
        operation_id="Update a user",))
@method_decorator(
    name='patch', decorator=swagger_auto_schema(
        operation_description="Patch a user",
        operation_id="Patch a user",))
class RetrieveUpdateUserView(generics.RetrieveUpdateAPIView):
    """Get or Update the authenticated user"""

    permission_classes = [permissions.IsAuthenticated,
                          RetrieveUpdateUserViewPermissions]
    serializer_class = CompleteUserSerializer

    def get_object(self):
        username = self.request.parser_context['kwargs']['username']
        return User.objects.get(username=username)

    def get(self, request, username):

        user = User.objects.get(username=username)

        if user.user_type == User.TYPE_ORGANIZATION:
            organization = Organization.objects.get(username=username)
            serializer = OrganizationSerializer(organization)
        else:
            if request.user == user:
                serializer = CompleteUserSerializer(user)
            else:
                serializer = PublicInfoUserSerializer(user)

        return Response(serializer.data)
