"""Business names for existing disposable seed records; identifiers stay stable."""

import os

from django.apps import apps
from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction

from .concurrency import compare_and_swap

SEED_LABEL_RENAMES = (
    ("courses.Course", "title", "P03 课程协作实践", "课程协作实践"),
    ("labtemplates.Template", "name", "P05 容器实验模板", "容器实验模板"),
    ("labtemplates.Template", "name", "P16 真实工作区模板", "真实工作区模板"),
    ("labtemplates.Template", "name", "T03 本地算法实验模板", "本地算法实验模板"),
    ("reviews.Rubric", "name", "P05 实验评分量规", "实验评分量规"),
    ("reviews.RubricVersion", "title", "P05 初始评分版本", "初始评分版本"),
    ("experiments.TaskPublication", "title", "P06 个人实验任务", "个人实验任务"),
    ("experiments.TaskPublication", "title", "P07 FakeRuntime 任务", "模拟环境实验任务"),
    ("experiments.TaskPublication", "title", "T03 本地算法运行任务", "本地算法运行任务"),
    ("governance.RuntimeAdapter", "name", "本地 P05 容器运行时", "本地容器运行环境"),
    ("governance.RuntimeAdapter", "name", "P07 Local FakeRuntime", "本地模拟实验环境"),
    ("governance.RuntimeAdapter", "name", "P16 本地 Docker 真实工作区", "本地 Docker 真实工作区"),
    ("governance.RuntimeAdapter", "name", "T03 本地 Docker 算法运行时", "本地 Docker 算法运行环境"),
    ("governance.ResourceProfile", "name", "P05 标准容器规格", "标准容器规格"),
    ("governance.ResourceProfile", "name", "P16 Python 工作区规格", "Python 工作区规格"),
    ("governance.ResourceProfile", "name", "T03 Python 算法规格", "Python 算法规格"),
    ("agents.KnowledgeBase", "name", "P12 Integration Knowledge", "课程集成验证知识库"),
    ("agents.EvalSuite", "name", "P12 platform safety baseline", "平台安全基线"),
    ("accounts.User", "display_name", "P10 Similarity Peer", "报告相似度验证学生"),
)


@transaction.atomic
def rename_seed_labels() -> int:
    if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
        raise CommandError("seed label renaming is restricted to disposable environments")
    changed = 0
    for model_name, field, previous, current in SEED_LABEL_RENAMES:
        model = apps.get_model(model_name)
        for row in model.objects.filter(**{field: previous}).select_for_update():
            compare_and_swap(
                model,
                pk=row.pk,
                expected_version=row.row_version,
                changes={field: current},
            )
            changed += 1
    return changed
