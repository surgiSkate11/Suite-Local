import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from suitelocal.main import certificate_stores, main


def test_each_business_gets_its_certificate_file_under_the_data_directory(tmp_path):
    stores = certificate_stores(tmp_path)

    assert stores(1).path == tmp_path / "certificates" / "business-1.bin"
    assert stores(7).path == tmp_path / "certificates" / "business-7.bin"
    assert stores(1).exists() is False


def test_smoke_test_flag_exits_zero_without_touching_the_user_database(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    assert main(["--smoke-test"]) == 0

    assert capsys.readouterr().err == ""
    assert not (tmp_path / "AppData").exists()
