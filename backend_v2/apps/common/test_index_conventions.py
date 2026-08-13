from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.test import SimpleTestCase

DJANGO_CONTRIB_APPS = frozenset(
    {
        "admin",
        "auth",
        "contenttypes",
        "sessions",
        "messages",
        "staticfiles",
    }
)


def _is_checked_model(model) -> bool:
    meta = model._meta
    if meta.proxy or not meta.managed or meta.auto_created:
        return False
    if meta.app_label in DJANGO_CONTRIB_APPS:
        return False
    return True


def _full_covering_field_tuples(model) -> list[tuple[str, ...]]:
    """Indexes/uniques that cover every row (no partial predicate)."""
    tuples: list[tuple[str, ...]] = []
    for fields in model._meta.unique_together:
        names = tuple(fields)
        if names:
            tuples.append(names)
    for constraint in model._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint):
            continue
        if constraint.condition is not None:
            continue
        names = tuple(constraint.fields)
        if names:
            tuples.append(names)
    for index in model._meta.indexes:
        if getattr(index, "condition", None) is not None:
            continue
        names = tuple(index.fields)
        if names:
            tuples.append(names)
    return tuples


class RedundantIndexConventionTests(SimpleTestCase):
    def test_foreign_keys_do_not_keep_db_index_when_covered(self):
        violations = []
        for model in apps.get_models():
            if not _is_checked_model(model):
                continue
            covering = _full_covering_field_tuples(model)
            for field in model._meta.local_fields:
                if not isinstance(field, models.ForeignKey):
                    continue
                if isinstance(field, models.OneToOneField):
                    continue
                if not field.db_index:
                    continue
                for cols in covering:
                    if cols[0] != field.name:
                        continue
                    if len(cols) >= 1 and (len(cols) > 1 or cols == (field.name,)):
                        violations.append(
                            f"{model._meta.label}.{field.name} db_index=True is covered by {cols}"
                        )
                        break
        self.assertEqual(violations, [], "\n".join(violations))

    def test_meta_indexes_are_not_redundant_with_unique_or_wider_index(self):
        violations = []
        for model in apps.get_models():
            if not _is_checked_model(model):
                continue
            uniques: list[tuple[str, ...]] = []
            for fields in model._meta.unique_together:
                uniques.append(tuple(fields))
            for constraint in model._meta.constraints:
                if isinstance(constraint, models.UniqueConstraint) and constraint.condition is None:
                    uniques.append(tuple(constraint.fields))
            named_indexes = []
            for index in model._meta.indexes:
                if getattr(index, "condition", None) is not None:
                    continue
                named_indexes.append((index.name, tuple(index.fields)))

            covering = uniques + [fields for _, fields in named_indexes]
            for name, fields in named_indexes:
                if fields in uniques:
                    violations.append(
                        f"{model._meta.label} index {name} {fields} duplicates UniqueConstraint/unique_together"
                    )
                    continue
                if len(fields) == 1:
                    try:
                        field = model._meta.get_field(fields[0])
                    except FieldDoesNotExist:
                        field = None
                    if (
                        isinstance(field, models.ForeignKey)
                        and not isinstance(field, models.OneToOneField)
                        and field.db_index
                    ):
                        violations.append(
                            f"{model._meta.label} index {name} {fields} duplicates implicit FK index"
                        )
                        continue
                for other in covering:
                    if other == fields:
                        continue
                    if len(other) > len(fields) and other[: len(fields)] == fields:
                        violations.append(
                            f"{model._meta.label} index {name} {fields} is a prefix of {other}"
                        )
                        break
        self.assertEqual(violations, [], "\n".join(violations))
