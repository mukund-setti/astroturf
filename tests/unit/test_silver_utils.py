from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.silver import ensure_schema


def test_ensure_schema_non_existent_table(tmp_path: Path) -> None:
    # If the Delta table doesn't exist, ensure_schema should return without raising/doing anything.
    non_existent = tmp_path / "does_not_exist"
    schema = pa.schema([pa.field("id", pa.string())])
    ensure_schema(non_existent, schema, allow_destructive=True)
    assert not non_existent.exists()


def test_ensure_schema_identical_schemas(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=True),
    ])
    
    # Create empty table with the schema
    empty_tbl = pa.Table.from_pylist([], schema=schema)
    write_deltalake(str(table_path), empty_tbl, mode="overwrite")
    
    # Test: ensure_schema should return without error since they match
    ensure_schema(table_path, schema, allow_destructive=False)
    
    # Assert schema remains identical
    dt = DeltaTable(str(table_path))
    assert dt.to_pyarrow_table().schema.names == ["id", "value"]


def test_ensure_schema_additive_evolution(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    
    # 1. Write initial table (Old Schema)
    old_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=True),
    ])
    data = pa.Table.from_pydict({"id": ["1", "2"], "value": [10, 20]}, schema=old_schema)
    write_deltalake(str(table_path), data, mode="overwrite")
    
    # 2. Define Expected Schema (New Schema with extra fields)
    new_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=True),
        pa.field("description", pa.string(), nullable=True),
        pa.field("active", pa.bool_(), nullable=True),
    ])
    
    # Test: Should raise ValueError if allow_destructive is False
    with pytest.raises(ValueError) as exc_info:
        ensure_schema(table_path, new_schema, allow_destructive=False)
    assert "is missing new fields" in str(exc_info.value)
    
    # Test: Should succeed if allow_destructive is True
    ensure_schema(table_path, new_schema, allow_destructive=True)
    
    # Verify the table schema has evolved and contains nulls for missing values
    dt = DeltaTable(str(table_path))
    evolved_tbl = dt.to_pyarrow_table()
    assert evolved_tbl.schema == new_schema
    assert evolved_tbl.to_pylist() == [
        {"id": "1", "value": 10, "description": None, "active": None},
        {"id": "2", "value": 20, "description": None, "active": None},
    ]


def test_ensure_schema_rejects_missing_column_on_agent_side(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    
    # Table has 'extra_field'
    old_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("extra_field", pa.string(), nullable=True),
    ])
    data = pa.Table.from_pydict({"id": ["1"], "extra_field": ["hello"]}, schema=old_schema)
    write_deltalake(str(table_path), data, mode="overwrite")
    
    # Expected schema is missing 'extra_field' (non-additive removal)
    expected_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
    ])
    
    with pytest.raises(ValueError) as exc_info:
        ensure_schema(table_path, expected_schema, allow_destructive=True)
    assert "non-additive change. Columns ['extra_field'] exist on disk but are missing" in str(exc_info.value)


def test_ensure_schema_rejects_type_changes(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    
    # 'value' is int64
    old_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=True),
    ])
    data = pa.Table.from_pydict({"id": ["1"], "value": [10]}, schema=old_schema)
    write_deltalake(str(table_path), data, mode="overwrite")
    
    # Expected schema wants 'value' as float64
    expected_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.float64(), nullable=True),
    ])
    
    with pytest.raises(ValueError) as exc_info:
        ensure_schema(table_path, expected_schema, allow_destructive=True)
    assert "non-additive type change for field 'value'" in str(exc_info.value)


def test_ensure_schema_rejects_nullability_changes(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    
    # 'value' is nullable=True
    old_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=True),
    ])
    data = pa.Table.from_pydict({"id": ["1"], "value": [10]}, schema=old_schema)
    write_deltalake(str(table_path), data, mode="overwrite")
    
    # Expected schema wants 'value' as nullable=False
    expected_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=False),
    ])
    
    with pytest.raises(ValueError) as exc_info:
        ensure_schema(table_path, expected_schema, allow_destructive=True)
    assert "non-additive nullability change for field 'value'" in str(exc_info.value)


def test_ensure_schema_rejects_new_non_nullable_fields(tmp_path: Path) -> None:
    table_path = tmp_path / "test_table"
    
    old_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
    ])
    data = pa.Table.from_pydict({"id": ["1"]}, schema=old_schema)
    write_deltalake(str(table_path), data, mode="overwrite")
    
    # Expected schema wants a new field, but makes it non-nullable (which existing data cannot satisfy)
    expected_schema = pa.schema([
        pa.field("id", pa.string(), nullable=True),
        pa.field("new_field", pa.string(), nullable=False),
    ])
    
    with pytest.raises(ValueError) as exc_info:
        ensure_schema(table_path, expected_schema, allow_destructive=True)
    assert "new fields ['new_field'] are non-nullable" in str(exc_info.value)
