"""Attachment content extraction, cleaning, chunking, and _ai_read formatting.
Refactored from et-addons/ai/models/ir_attachment.py and et-addons/ai/models/models.py.
"""
import base64
import hashlib
import io
import logging
import mimetypes
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_logger = logging.getLogger(__name__)

AI_SUPPORTED_IMG_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}
AI_MAX_PDF_PAGES = 5


def compute_checksum(data: bytes) -> str:
    """Compute SHA-1 checksum of binary data (identical to Odoo ir.attachment._compute_checksum)."""
    return hashlib.sha1(data or b"").hexdigest()


def guess_file_mimetype(filename: str, data: bytes | None = None) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    ext = Path(filename).suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".txt": "text/plain",
        ".xml": "application/xml",
        ".html": "text/html",
    }
    return mapping.get(ext, "application/octet-stream")


def _extract_para_text(p_elem) -> str:
    parts = []
    for node in p_elem.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
        elif node.tag.endswith("}br") or node.tag.endswith("}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def extract_text_from_docx(data: bytes) -> str:
    """Extract paragraphs and structured tables from a .docx file."""
    lines: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                return ""
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)

            # Iterate body elements in document order (paragraphs and tables)
            body = next((el for el in tree.iter() if el.tag.endswith("}body")), tree)
            for child in body:
                if child.tag.endswith("}p"):
                    para_text = _extract_para_text(child)
                    if para_text:
                        lines.append(para_text)
                elif child.tag.endswith("}tbl"):
                    table_rows = []
                    for row in child:
                        if row.tag.endswith("}tr"):
                            tcs = [c for c in row if c.tag.endswith("}tc")]
                            if len(tcs) == 1:
                                # Single-column box: preserve paragraph line breaks
                                paras = [
                                    _extract_para_text(p)
                                    for p in tcs[0]
                                    if p.tag.endswith("}p")
                                ]
                                box_text = "\n".join(p for p in paras if p)
                                if box_text:
                                    table_rows.append(box_text)
                            else:
                                cells = []
                                for cell in tcs:
                                    paras = [
                                        _extract_para_text(p)
                                        for p in cell
                                        if p.tag.endswith("}p")
                                    ]
                                    cell_str = " ".join(" ".join(p for p in paras if p).split())
                                    cells.append(cell_str)
                                if any(cells):
                                    table_rows.append(" | ".join(cells))
                    if table_rows:
                        lines.append("\n".join(table_rows))
    except Exception as e:
        _logger.warning("Failed to parse DOCX: %s", e)
    return "\n".join(lines)


def extract_text_from_pdf(data: bytes) -> str:
    """Extract text from PDF bytes using pypdf/pymupdf or pdftotext fallback."""
    # Try pypdf / fitz if available
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=data, filetype="pdf")
        pages_text = [page.get_text("text") for page in doc]
        text = "\n\n".join(pages_text).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as e:
        _logger.debug("PyMuPDF extraction error: %s", e)

    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages_text).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as e:
        _logger.debug("pypdf extraction error: %s", e)

    # Fallback to system pdftotext (poppler-utils)
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            res = subprocess.run(
                ["pdftotext", "-layout", tmp.name, "-"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    except Exception as e:
        _logger.debug("pdftotext fallback error: %s", e)

    return ""


def extract_attachment_content(data: bytes, filename: str, mimetype: str | None = None) -> str:
    """Extract indexable text content from attachment bytes."""
    mimetype = mimetype or guess_file_mimetype(filename, data)
    ext = Path(filename).suffix.lower()

    if ext == ".docx" or "wordprocessingml" in mimetype:
        content = extract_text_from_docx(data)
    elif ext == ".pdf" or mimetype == "application/pdf":
        content = extract_text_from_pdf(data)
    elif ext in (".txt", ".csv", ".xml", ".html", ".md") or mimetype.startswith("text/"):
        content = data.decode("utf-8", errors="replace")
    else:
        content = ""

    return content.strip()


def clean_text(text: str) -> str:
    """Clean up text content while preserving meaningful structure.
    Refactored from IrAttachment._clean_text in et-addons/ai/models/ir_attachment.py.
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n")

    lines = text.split("\n")
    result = []
    current_paragraph = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if current_paragraph:
                result.append(" ".join(current_paragraph))
                current_paragraph = []
            continue

        if (
            stripped.endswith(":")
            or "|" in stripped
            or stripped.startswith("Điều ")
            or stripped.startswith("ĐIỀU ")
            or (len(stripped) < 120 and stripped.endswith("."))
        ):
            if current_paragraph:
                result.append(" ".join(current_paragraph))
                current_paragraph = []
            result.append(stripped)
            continue

        current_paragraph.append(stripped)

    if current_paragraph:
        result.append(" ".join(current_paragraph))

    text = "\n".join(result)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = 1500,
    margin: int = 200,
    min_chunk_size: int = 600,
    max_chunk_size: int = 5000,
) -> list[str]:
    """Split text into chunks based on character count with a hard maximum limit.
    Refactored from IrAttachment._chunk_text in et-addons/ai/models/ir_attachment.py.
    """
    cleaned_text = clean_text(text)
    if not cleaned_text:
        return []
    chunks: list[str] = []
    paragraphs = cleaned_text.split("\n")

    current_chunk: list[str] = []
    current_length = 0

    def _add_chunk_enforcing_max_size(chunk_content: str):
        if len(chunk_content) <= max_chunk_size:
            chunks.append(chunk_content)
        else:
            words = chunk_content.split()
            temp_chunk = []
            temp_length = 0
            for word in words:
                word_length = len(word) + 1
                if temp_length + word_length > max_chunk_size:
                    if temp_chunk:
                        chunks.append(" ".join(temp_chunk))
                    temp_chunk = [word]
                    temp_length = len(word)
                else:
                    temp_chunk.append(word)
                    temp_length += word_length
            if temp_chunk:
                chunks.append(" ".join(temp_chunk))

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_length = len(para)

        if current_chunk and (current_length + para_length + 1 <= chunk_size + margin):
            current_chunk.append(para)
            current_length += para_length + 1
            continue

        if current_length >= chunk_size - margin:
            _add_chunk_enforcing_max_size("\n".join(current_chunk))
            current_chunk = [para]
            current_length = para_length
        else:
            if para_length > chunk_size:
                if current_chunk:
                    _add_chunk_enforcing_max_size("\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0
                sentences = re.split(r"(?<=[.!?])\s+", para)
                temp_chunk = []
                temp_length = 0

                for sentence in sentences:
                    sent_length = len(sentence)
                    if temp_length + sent_length + 1 > chunk_size:
                        if temp_chunk:
                            _add_chunk_enforcing_max_size(" ".join(temp_chunk))
                        temp_chunk = [sentence]
                        temp_length = sent_length
                    else:
                        temp_chunk.append(sentence)
                        temp_length += sent_length + 1

                if temp_chunk:
                    _add_chunk_enforcing_max_size(" ".join(temp_chunk))
            else:
                current_chunk.append(para)
                current_length += para_length + 1

    if current_chunk:
        last_chunk_content = "\n".join(current_chunk)
        if chunks and len(last_chunk_content) < min_chunk_size:
            if len(chunks[-1]) + len(last_chunk_content) + 1 <= max_chunk_size:
                chunks[-1] += "\n" + last_chunk_content
            else:
                _add_chunk_enforcing_max_size(last_chunk_content)
        else:
            _add_chunk_enforcing_max_size(last_chunk_content)

    return chunks


def build_ai_file_payloads(
    data: bytes,
    filename: str,
    mimetype: str | None = None,
    extracted_text: str | None = None,
    file_index: int = 1,
) -> list[dict]:
    """Prepare `files` list for LLMApiService following IrAttachment._ai_read in et-addons/ai/models/ir_attachment.py."""
    mimetype = mimetype or guess_file_mimetype(filename, data)
    ext = mimetype.split("/")[-1].lower()
    file_ref = f"<file_#{file_index}>"
    payloads: list[dict] = []

    if extracted_text is None:
        extracted_text = extract_attachment_content(data, filename, mimetype)

    # Always include extracted text if available (crucial for .docx and text-searchable PDFs)
    if extracted_text:
        payloads.append(
            {
                "mimetype": "text/plain",
                "value": f"Filename: {filename}\n{extracted_text}",
                "file_ref": file_ref,
            }
        )

    # Also attach native PDF or Image for multimodal vision inspection (tables, layout, stamps, signatures)
    if mimetype == "application/pdf":
        payloads.append(
            {
                "mimetype": "application/pdf",
                "value": base64.b64encode(data).decode("ascii"),
                "file_ref": f"<file_#{file_index}_pdf>",
            }
        )
    elif ext in AI_SUPPORTED_IMG_TYPES or mimetype.startswith("image/"):
        payloads.append(
            {
                "mimetype": mimetype,
                "value": base64.b64encode(data).decode("ascii"),
                "file_ref": f"<file_#{file_index}_img>",
            }
        )

    return payloads
