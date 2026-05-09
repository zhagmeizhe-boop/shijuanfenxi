import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.v1.endpoints.papers import _prepare_analysis_input
from app.services.ocr.base import IMAGE_MANIFEST_KIND
from app.services.ocr.mock_provider import MockOCRProvider


class FakeUpload:
    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self._content = content
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._content


def _image_bytes(fmt: str = "JPEG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 96), "white").save(output, format=fmt)
    return output.getvalue()


@pytest.mark.asyncio
async def test_prepare_analysis_input_writes_multi_image_manifest(tmp_path: Path):
    provider = MockOCRProvider()
    first = FakeUpload("page-b.jpg", _image_bytes("JPEG"), "image/jpeg")
    second = FakeUpload("page-a.png", _image_bytes("PNG"), "image/png")

    result = await _prepare_analysis_input(
        upload_dir=tmp_path,
        ocr_provider=provider,
        file=None,
        files=[first, second],
    )

    assert result.file_type == "images"
    assert result.page_count_hint == 2
    assert result.path.name == "input_manifest.json"

    manifest = json.loads(result.path.read_text(encoding="utf-8"))
    assert manifest["kind"] == IMAGE_MANIFEST_KIND
    assert [page["page_no"] for page in manifest["pages"]] == [1, 2]
    assert [page["original_filename"] for page in manifest["pages"]] == ["page-b.jpg", "page-a.png"]
    assert all(Path(page["path"]).exists() for page in manifest["pages"])

    loaded_pages = provider.load_image_manifest_pages(str(result.path))
    assert [page.page_no for page in loaded_pages] == [1, 2]
    assert [page.original_filename for page in loaded_pages] == ["page-b.jpg", "page-a.png"]


@pytest.mark.asyncio
async def test_prepare_analysis_input_accepts_single_image_file_field(tmp_path: Path):
    provider = MockOCRProvider()
    image = FakeUpload("single.jpg", _image_bytes("JPEG"), "image/jpeg")

    result = await _prepare_analysis_input(
        upload_dir=tmp_path,
        ocr_provider=provider,
        file=image,
        files=None,
    )

    assert result.file_type == "jpg"
    assert result.page_count_hint == 1
    assert result.path.name == "original.jpg"
    assert result.path.exists()


@pytest.mark.asyncio
async def test_prepare_analysis_input_rejects_single_and_multi_fields_together(tmp_path: Path):
    provider = MockOCRProvider()

    with pytest.raises(HTTPException) as exc_info:
        await _prepare_analysis_input(
            upload_dir=tmp_path,
            ocr_provider=provider,
            file=FakeUpload("paper.pdf", b"%PDF-1.4", "application/pdf"),
            files=[FakeUpload("page.jpg", _image_bytes("JPEG"), "image/jpeg")],
        )

    assert exc_info.value.status_code == 400
    assert "不能同时使用" in exc_info.value.detail


@pytest.mark.asyncio
async def test_prepare_analysis_input_rejects_pdf_in_multi_image_field(tmp_path: Path):
    provider = MockOCRProvider()

    with pytest.raises(HTTPException) as exc_info:
        await _prepare_analysis_input(
            upload_dir=tmp_path,
            ocr_provider=provider,
            file=None,
            files=[FakeUpload("paper.pdf", b"%PDF-1.4", "application/pdf")],
        )

    assert exc_info.value.status_code == 400
    assert "JPG/JPEG/PNG" in exc_info.value.detail


@pytest.mark.asyncio
async def test_prepare_analysis_input_rejects_too_many_images(tmp_path: Path):
    provider = MockOCRProvider()
    files = [
        FakeUpload(f"page-{index}.jpg", _image_bytes("JPEG"), "image/jpeg")
        for index in range(provider.upload_config.max_image_count + 1)
    ]

    with pytest.raises(HTTPException) as exc_info:
        await _prepare_analysis_input(
            upload_dir=tmp_path,
            ocr_provider=provider,
            file=None,
            files=files,
        )

    assert exc_info.value.status_code == 400
    assert "图片数量超过限制" in exc_info.value.detail


@pytest.mark.asyncio
async def test_prepare_analysis_input_rejects_webp(tmp_path: Path):
    provider = MockOCRProvider()

    with pytest.raises(HTTPException) as exc_info:
        await _prepare_analysis_input(
            upload_dir=tmp_path,
            ocr_provider=provider,
            file=None,
            files=[FakeUpload("page.webp", _image_bytes("PNG"), "image/webp")],
        )

    assert exc_info.value.status_code == 400
    assert "不支持的文件格式" in exc_info.value.detail
