from django.urls import path

from .views import (
    AutoCheckRuleView,
    CloneVersionView,
    PlatformPrecheckSummaryView,
    PrecheckRunListView,
    PrecheckView,
    PublishVersionView,
    TemplateAssetCollectionView,
    TemplateAssetCompleteView,
    TemplateAssetDetailView,
    TemplateChapterCollectionView,
    TemplateChapterDetailView,
    TemplateChapterReorderView,
    TemplateDetailView,
    TemplateListView,
    TemplateOptionsView,
    TemplateTaskCollectionView,
    TemplateTaskDetailView,
    TemplateTaskReorderView,
    TemplateVersionDetailView,
    TemplateVersionListView,
    WithdrawVersionView,
    ExperimentImageCollectionView,
    ExperimentImageDetailView,
    ExperimentImageEventsView,
    ExperimentImagePrepareView,
    ExperimentImageRetireView,
)

urlpatterns = [
    path("teaching/courses/<str:course_id>/experiment-images", ExperimentImageCollectionView.as_view()),
    path("teaching/courses/<str:course_id>/experiment-images/<str:image_id>", ExperimentImageDetailView.as_view()),
    path("teaching/courses/<str:course_id>/experiment-images/<str:image_id>/prepare", ExperimentImagePrepareView.as_view()),
    path("teaching/courses/<str:course_id>/experiment-images/<str:image_id>/events", ExperimentImageEventsView.as_view()),
    path("teaching/courses/<str:course_id>/experiment-images/<str:image_id>/retire", ExperimentImageRetireView.as_view()),
    path("teaching/courses/<str:course_id>/template-options", TemplateOptionsView.as_view()),
    path("teaching/courses/<str:course_id>/templates", TemplateListView.as_view()),
    path(
        "teaching/courses/<str:course_id>/templates/<str:template_id>", TemplateDetailView.as_view()
    ),
    path(
        "teaching/courses/<str:course_id>/templates/<str:template_id>/assets",
        TemplateAssetCollectionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/templates/<str:template_id>/assets/<str:asset_id>",
        TemplateAssetDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/templates/<str:template_id>/assets/<str:asset_id>/complete",
        TemplateAssetCompleteView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/templates/<str:template_id>/versions",
        TemplateVersionListView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>",
        TemplateVersionDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/auto-check-rules",
        AutoCheckRuleView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/chapters",
        TemplateChapterCollectionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/chapters/reorder",
        TemplateChapterReorderView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-chapters/<str:chapter_id>",
        TemplateChapterDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-chapters/<str:chapter_id>/tasks",
        TemplateTaskCollectionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-chapters/<str:chapter_id>/tasks/reorder",
        TemplateTaskReorderView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-tasks/<str:task_id>",
        TemplateTaskDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/precheck",
        PrecheckView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/precheck-runs",
        PrecheckRunListView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/publish",
        PublishVersionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/withdraw",
        WithdrawVersionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/template-versions/<str:version_id>/clone",
        CloneVersionView.as_view(),
    ),
    path("platform/template-prechecks/summary", PlatformPrecheckSummaryView.as_view()),
]
