import logging
from typing import List

import qfieldcloud.core.models as models
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from qfieldcloud.core import exceptions

logger = logging.getLogger(__name__)


@transaction.atomic
def apply_deltas(
    project: "models.Project",
    user: "models.User",
    project_file: str,
    overwrite_conflicts: bool,
    delta_ids: List[str] = [],
) -> List["models.ApplyJob"]:
    """Apply a deltas"""

    logger.info(
        f"Requested apply_deltas on {project} with {project_file}; overwrite_conflicts: {overwrite_conflicts}; delta_ids: {delta_ids}"
    )

    # 1. Check if there are any pending deltas.
    # We need to call .select_for_update() to make sure there would not be a concurrent
    # request that will try to apply these deltas.
    pending_deltas = models.Delta.objects.select_for_update().filter(
        project=project,
        last_status=models.Delta.Status.PENDING,
    )

    # 1.1. Filter only the deltas of interest.
    if len(delta_ids) > 0:
        pending_deltas.filter(pk__in=delta_ids)

    # 2. If there are no pending deltas, do not create a new job and return.
    if pending_deltas.count() == 0:
        return None

    # 3. Find all the pending or queued jobs in the queue.
    # If an "apply_delta" job is in a "started" status, we don't know how far the execution reached
    # so we better assume the deltas will reach a non-"pending" status.
    apply_jobs = models.ApplyJob.objects.filter(
        project=project,
        status=[
            models.Job.Status.PENDING,
            models.Job.Status.QUEUED,
        ],
    )

    # 4. Check whether there are jobs found in the queue and exclude all deltas that are part of any pending job.
    if apply_jobs.count() > 0:
        pending_deltas = pending_deltas.exclude(jobs_to_apply__in=apply_jobs)

    # 5. If there are no pending deltas, do not create a new job and return.
    deltas_count = pending_deltas.count()
    if deltas_count == 0:
        return None

    # 6. There are pending deltas that are not part of any pending job. So we create one.
    apply_jobs = []
    for i in range(deltas_count // settings.APPLY_DELTAS_LIMIT + 1):
        offset = settings.APPLY_DELTAS_LIMIT * i
        limit = max(settings.APPLY_DELTAS_LIMIT * (i + 1), deltas_count)

        if offset == limit:
            break

        apply_job = models.ApplyJob.objects.create(
            project=project,
            created_by=user,
            overwrite_conflicts=overwrite_conflicts,
        )

        models.ApplyJobDelta.objects.bulk_create(
            [
                models.ApplyJobDelta(
                    apply_job=apply_job,
                    delta=delta,
                )
                for delta in pending_deltas.order_by("created_at")[offset:limit]
            ]
        )

        apply_jobs.append(apply_job)

    # 7. return the created job
    return apply_jobs


def repackage(project: "models.Project", user: "models.User") -> "models.PackageJob":
    """Returns an unfinished or freshly created package job.

    Checks if there is already an unfinished package job and returns it,
    or creates a new package job and returns it.
    """
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    # Check if active package job already exists
    query = Q(project=project) & (
        Q(status=models.PackageJob.Status.PENDING)
        | Q(status=models.PackageJob.Status.QUEUED)
        | Q(status=models.PackageJob.Status.STARTED)
    )

    if models.PackageJob.objects.filter(query).count():
        return models.PackageJob.objects.get(query)

    package_job = models.PackageJob.objects.create(project=project, created_by=user)

    return package_job


def repackage_if_needed(
    project: "models.Project", user: "models.User"
) -> "models.PackageJob":
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    if project.needs_repackaging:
        package_job = repackage(project, user)
    else:
        package_job = (
            models.PackageJob.objects.filter(project=project)
            .order_by("started_at")
            .get()
        )

    return package_job
