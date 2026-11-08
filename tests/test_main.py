import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from suitelocal.main import certificate_stores


def test_each_business_gets_its_certificate_file_under_the_data_directory(tmp_path):
    stores = certificate_stores(tmp_path)

    assert stores(1).path == tmp_path / "certificates" / "business-1.bin"
    assert stores(7).path == tmp_path / "certificates" / "business-7.bin"
    assert stores(1).exists() is False
