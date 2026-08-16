"""Library hygiene / audit (read-only) — volume gaps, duplicates, structure flags."""

from .volume_report import (
    build_volume_report,
    format_number_ranges,
    resolve_completion_state,
)
from .duplicates import cluster_duplicate_series, score_duplicate_pair, dup_group_key
from .dup_script import (
    build_duplicate_folder_script,
    inventory_folder_path_prefix_from_config,
    normalize_inventory_folder_path_prefix,
    normalize_inventory_folder_trash,
    resolve_script_folder_path,
)
from .external_ids import series_has_external_id
from .catalog_count import (
    resolve_catalog_expected,
    missing_volume_numbers,
    apply_catalog_override,
)
from .series_identity import (
    merge_series_identity,
    extract_provider_ids,
    build_score_candidate_from_identity,
    identity_has_external_id,
    series_folder_path,
)
from .export_csv import (
    volume_report_to_csv,
    volume_report_to_txt,
    duplicates_to_csv,
    duplicates_to_txt,
    missing_volumes_to_csv,
    missing_volumes_to_txt,
)

__all__ = [
    "build_volume_report",
    "format_number_ranges",
    "resolve_completion_state",
    "cluster_duplicate_series",
    "score_duplicate_pair",
    "dup_group_key",
    "build_duplicate_folder_script",
    "inventory_folder_path_prefix_from_config",
    "normalize_inventory_folder_path_prefix",
    "normalize_inventory_folder_trash",
    "resolve_script_folder_path",
    "series_folder_path",
    "series_has_external_id",
    "resolve_catalog_expected",
    "missing_volume_numbers",
    "apply_catalog_override",
    "merge_series_identity",
    "extract_provider_ids",
    "build_score_candidate_from_identity",
    "identity_has_external_id",
    "volume_report_to_csv",
    "volume_report_to_txt",
    "duplicates_to_csv",
    "duplicates_to_txt",
    "missing_volumes_to_csv",
    "missing_volumes_to_txt",
]
