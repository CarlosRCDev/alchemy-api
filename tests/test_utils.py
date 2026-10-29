from alchemy_api.utils import DbExecption, error, read_file_reverse


def test_read_file_reverse_across_chunks(tmp_path):
    # Lines long enough to cross several 8192-byte chunks
    expected = [f"line-{i:05d}-" + "x" * 50 for i in range(500)]
    path = tmp_path / "file.log"
    path.write_text("\n".join(expected) + "\n", encoding="utf-8")
    assert read_file_reverse(path) == expected[::-1]


def test_read_file_reverse_n_line(tmp_path):
    path = tmp_path / "file.log"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    assert read_file_reverse(path, 2) == ["c", "b"]


def test_dbexception():
    exc = DbExecption(error("boom", 404, False))
    assert str(exc) == "boom"
    assert exc.status_code == 404
    assert exc.trace is None
    exc = DbExecption(error("boom"))
    assert exc.status_code == 400
    assert exc.trace is None
