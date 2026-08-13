from importlib import import_module
from inspect import getsource
from pathlib import Path

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.migrations.operations.fields import AlterField
from django.db.migrations.operations.models import RemoveIndex
from django.db.migrations.operations.special import RunPython, SeparateDatabaseAndState
from django.test import SimpleTestCase

from apps.common.index_migrations import drop_unconstrained_fk_indexes

# Already applied on production via AlterField; do not rewrite that file.
_APPLIED_ALTERFIELD_DROP_MIGRATIONS = frozenset(
    {
        "accounts/migrations/0009_otpchallenge_drop_redundant_tenant_index.py",
    }
)

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


def _database_operations(operations):
    for op in operations:
        if isinstance(op, SeparateDatabaseAndState):
            yield from op.database_operations
        else:
            yield op


class DropRedundantIndexMigrationTests(SimpleTestCase):
    def test_unapplied_drop_redundant_migrations_do_not_alter_fk_on_database(self):
        apps_root = Path(__file__).resolve().parents[1]
        violations = []
        found = 0
        for path in sorted(apps_root.rglob("*drop_redundant*.py")):
            rel = path.relative_to(apps_root).as_posix()
            if rel in _APPLIED_ALTERFIELD_DROP_MIGRATIONS:
                continue
            found += 1
            module_name = ".".join(("apps", *Path(rel).with_suffix("").parts))
            module = import_module(module_name)
            for op in _database_operations(module.Migration.operations):
                if isinstance(op, AlterField):
                    violations.append(f"{module_name} runs AlterField on the database")
                elif not isinstance(op, (RemoveIndex, RunPython)):
                    violations.append(
                        f"{module_name} has unexpected database operation {type(op).__name__}"
                    )
        self.assertGreater(found, 0)
        self.assertEqual(violations, [], "\n".join(violations))

    def test_index_drop_helper_only_drops_unconstrained_nonunique_indexes(self):
        source = getsource(drop_unconstrained_fk_indexes)
        self.assertIn("indisunique IS FALSE", source)
        self.assertIn("indisprimary IS FALSE", source)
        self.assertIn("pg_constraint", source)
        self.assertIn("DROP INDEX IF EXISTS", source)
        self.assertNotIn("DROP CONSTRAINT", source)
        self.assertNotIn("DROP TABLE", source)
        self.assertNotIn("DELETE FROM", source)
