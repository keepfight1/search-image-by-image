import io
import zipfile

from data_eval.acquire import download


def test_single_file_zip_response(tmp_path, monkeypatch):
    content = b"image-bytes"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("photo.jpg", content)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield archive.getvalue()
    monkeypatch.setattr("data_eval.acquire.requests.get", lambda *args, **kwargs: Response())
    target = tmp_path / "photo.jpg"
    download("https://example.invalid/image", target, expected_size=len(content))
    assert target.read_bytes() == content
    # Cache should avoid another network request.
    monkeypatch.setattr("data_eval.acquire.requests.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    download("https://example.invalid/image", target, expected_size=len(content))
