from pathlib import PurePath

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http.response import HttpResponseRedirect
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from qfieldcloud.core import exceptions, permissions_utils, serializers, utils
from qfieldcloud.core.models import ExportJob, Project
from rest_framework import permissions, views
from rest_framework.response import Response


class ExportViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(request, "projectid")
        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            return False
        user = request.user
        return permissions_utils.can_read_files(user, project)


@method_decorator(
    name="post",
    decorator=swagger_auto_schema(
        operation_description="Launch QField export project",
        operation_id="Launch qfield export",
    ),
)
@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="Get QField export status",
        operation_id="Get qfield export status",
    ),
)
class ExportView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, ExportViewPermissions]

    def post(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)

        if not project_obj.project_filename:
            raise exceptions.NoQGISProjectError()

        # Check if active export job already exists
        # TODO: !!!!!!!!!!!! cache results for some minutes
        query = Q(project=project_obj) & (
            Q(status=ExportJob.Status.PENDING)
            | Q(status=ExportJob.Status.QUEUED)
            | Q(status=ExportJob.Status.STARTED)
        )

        # NOTE uncomment to enforce job creation
        # ExportJob.objects.filter(query).delete()

        if ExportJob.objects.filter(query).exists():
            serializer = serializers.ExportJobSerializer(ExportJob.objects.get(query))
            return Response(serializer.data)

        export_job = ExportJob.objects.create(
            project=project_obj, created_by=self.request.user
        )

        # TODO: check if user is allowed otherwise ERROR 403
        serializer = serializers.ExportJobSerializer(export_job)

        return Response(serializer.data)

    def get(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)

        export_job = (
            ExportJob.objects.filter(project=project_obj).order_by("updated_at").last()
        )

        serializer = serializers.ExportJobSerializer(export_job)
        return Response(serializer.data)


@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="List QField project files",
        operation_id="List qfield project files",
    ),
)
class ListFilesView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, ExportViewPermissions]

    def get(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)

        # Check if the project was exported at least once
        if not ExportJob.objects.filter(
            project=project_obj, status=ExportJob.Status.FINISHED
        ):
            raise exceptions.InvalidJobError(
                "Project files have not been exported for the provided project id"
            )

        export_job = (
            ExportJob.objects.filter(
                project=project_obj, status=ExportJob.Status.FINISHED
            )
            .order_by("updated_at")
            .last()
        )

        assert export_job

        # Obtain the bucket object
        bucket = utils.get_s3_bucket()

        export_prefix = "projects/{}/export/".format(projectid)

        files = []
        for obj in bucket.objects.filter(Prefix=export_prefix):
            path = PurePath(obj.key)

            # We cannot be sure of the metadata's first letter case
            # https://github.com/boto/boto3/issues/1709
            metadata = obj.Object().metadata
            if "sha256sum" in metadata:
                sha256sum = metadata["sha256sum"]
            else:
                sha256sum = metadata["Sha256sum"]

            files.append(
                {
                    # Get the path of the file relative to the export directory
                    "name": str(path.relative_to(*path.parts[:3])),
                    "size": obj.size,
                    "sha256": sha256sum,
                }
            )

        steps = export_job.feedback.get("steps", [])
        layers = (
            steps[1]["outputs"]["layer_checks"]
            if len(steps) > 2 and steps[1].get("stage", 1) == 2
            else None
        )

        return Response(
            {
                "files": files,
                "layers": layers,
                "exported_at": export_job.updated_at,
                "export_id": export_job.pk,
            }
        )


@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="Download file for QField",
        operation_id="Download qfield file",
    ),
)
class DownloadFileView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, ExportViewPermissions]

    def get(self, request, projectid, filename):

        project_obj = Project.objects.get(id=projectid)

        # Check if the project was exported at least once
        if not ExportJob.objects.filter(
            project=project_obj,
            status=ExportJob.Status.FINISHED,
        ):
            raise exceptions.InvalidJobError(
                "Project files have not been exported for the provided project id"
            )

        filekey = utils.safe_join("projects/{}/export/".format(projectid), filename)

        url = utils.get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Key": filekey,
                "Bucket": utils.get_s3_bucket().name,
                "ResponseContentType": "application/force-download",
                "ResponseContentDisposition": f'attachment;filename="{filename}"',
            },
            ExpiresIn=60,
            HttpMethod="GET",
        )

        return HttpResponseRedirect(url)
