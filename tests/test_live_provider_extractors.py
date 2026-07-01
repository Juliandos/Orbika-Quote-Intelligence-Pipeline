from pathlib import Path

from tools import provider_refresh


def test_provider_refresh_knows_all_live_extractors() -> None:
    provider_ids = [provider_id for provider_id, _script in provider_refresh.CATALOG_EXTRACTOR_SCRIPTS]
    assert len(provider_ids) == 29
    assert len(set(provider_ids)) == 29


def test_live_extractor_scripts_exist() -> None:
    for _provider_id, script_path in provider_refresh.CATALOG_EXTRACTOR_SCRIPTS:
        assert Path(script_path).exists(), script_path


def test_live_extractors_do_not_depend_on_deleted_generic_module() -> None:
    for _provider_id, script_path in provider_refresh.CATALOG_EXTRACTOR_SCRIPTS:
        content = Path(script_path).read_text(encoding="utf-8")
        assert "generic_seeded_catalog_extractor" not in content


def test_seeded_support_module_exists() -> None:
    assert Path("tools/seeded_catalog_support.py").exists()
