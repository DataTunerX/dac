from langchain_community.document_loaders.base import BaseLoader
from typing import List, Dict, Optional, Union, Any, Literal
from langchain.schema import Document
import logging
import os
import time
import tempfile
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
import json
from strenum import StrEnum
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MarkdownProcessor")

class MinerUContentType(StrEnum):
    IMAGE = "image"
    TABLE = "table"
    TEXT = "text"
    EQUATION = "equation"


class MinerULoader(BaseLoader):

    def __init__(self, file_path: Union[str, Path], output_dir: Optional[str] = None ,method: Optional[str] = "auto", lang: Optional[str] = None):
    	self.mineru_path = Path("mineru")
    	self.file_path = file_path
    	self.output_dir = output_dir
    	self.method = method
    	self.lang = lang

    def load(self) -> List[Document]:
        text = ""

        pdf = Path(self.file_path)

        if self.output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="mineru_pdf_"))
            created_tmp_dir = True

        logger.info(f"[MinerU] Output directory: {out_dir}")

        self.run_mineru(pdf, out_dir, method=self.method, lang=self.lang)

        outputs = self.read_md_output(out_dir, pdf.stem, method=self.method)

        documents = self.split_document_with_langchain_markdown_concat_headers(outputs, 1000, 200, "md")   

        return documents

    def run_mineru(self, input_path: Path, output_dir: Path, method: str = "auto", lang: Optional[str] = None):
        cmd = [str(self.mineru_path), "-p", str(input_path), "-o", str(output_dir), "-m", method]
        if lang:
            cmd.extend(["-l", lang])

        logger.info(f"[MinerU] Running command: {' '.join(cmd)}")

        subprocess_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "ignore",
            "bufsize": 1,
        }

        process = subprocess.Popen(cmd, **subprocess_kwargs)
        stdout_queue, stderr_queue = Queue(), Queue()

        def enqueue_output(pipe, queue, prefix):
            for line in iter(pipe.readline, ""):
                if line.strip():
                    queue.put((prefix, line.strip()))
            pipe.close()

        threading.Thread(target=enqueue_output, args=(process.stdout, stdout_queue, "STDOUT"), daemon=True).start()
        threading.Thread(target=enqueue_output, args=(process.stderr, stderr_queue, "STDERR"), daemon=True).start()

        while process.poll() is None:
            for q in (stdout_queue, stderr_queue):
                try:
                    while True:
                        prefix, line = q.get_nowait()
                        if prefix == "STDOUT":
                            logger.info(f"[MinerU] {line}")
                        else:
                            logger.warning(f"[MinerU] {line}")
                except Empty:
                    pass
            time.sleep(0.1)

        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"[MinerU] Process failed with exit code {return_code}")
        logger.info("[MinerU] Command completed successfully.")


    def read_md_output(self, output_dir: Path, file_stem: str, method: str = "auto") -> list[dict[str, Any]]:
        subdir = output_dir / file_stem / method
        md_file = subdir / f"{file_stem}.md"

        if not md_file.exists():
            raise FileNotFoundError(f"[MinerU] Missing output file: {md_file}")

        with open(md_file, "r", encoding="utf-8") as f:
            data = f.read()

        return data


    def read_json_output(self, output_dir: Path, file_stem: str, method: str = "auto") -> list[dict[str, Any]]:
        subdir = output_dir / file_stem / method
        json_file = subdir / f"{file_stem}_content_list.json"

        if not json_file.exists():
            raise FileNotFoundError(f"[MinerU] Missing output file: {json_file}")

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            for key in ("img_path", "table_img_path", "equation_img_path"):
                if key in item and item[key]:
                    item[key] = str((subdir / item[key]).resolve())
        return data

    #Using Langchain to split markdown files into chunks, where each chunk contains all the headers it belongs to. For example, if the text belongs to header 3, then it would be header1 + header2 + header3 + text.
    def split_document_with_langchain_markdown_concat_headers(self,markdown_content, chunk_size, chunk_overlap, spliter) -> List[Document]:
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
            ("#####", "Header 5"),
            ("######", "Header 6"),
        ]

        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on)
        md_header_splits = markdown_splitter.split_text(markdown_content)

        split_docs = []
        if spliter == "md":
            split_docs = md_header_splits

        if spliter == "md-txt":
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            split_docs = text_splitter.split_documents(md_header_splits)

        new_array = []

        for doc in split_docs:
            parts = []
            
            # Add the value of Header 1
            if 'Header 1' in doc.metadata:
                parts.append(doc.metadata['Header 1'])
            
            # Add the value of Header 2
            if 'Header 2' in doc.metadata:
                parts.append(doc.metadata['Header 2'])
            
            # Add the value of Header 3（if exist）
            if 'Header 3' in doc.metadata:
                parts.append(doc.metadata['Header 3'])

            # Add the value of Header 4（if exist）
            if 'Header 4' in doc.metadata:
                parts.append(doc.metadata['Header 4'])

            # Add the value of Header 5（if exist）
            if 'Header 5' in doc.metadata:
                parts.append(doc.metadata['Header 5'])

            # Add the value of Header 6（if exist）
            if 'Header 6' in doc.metadata:
                parts.append(doc.metadata['Header 6'])
            
            parts.append(doc.page_content)

            new_doc = Document(
                page_content='\n'.join(parts),
                metadata=doc.metadata.copy()
            )
            new_array.append(new_doc)

        return new_array

    # Use Langchain to split markdown files into chunks, where each chunk contains the headers for its own text.
    def split_document_with_langchain_markdown(self,markdown_content, chunk_size, chunk_overlap, spliter) -> List[Document]:
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
            ("#####", "Header 5"),
            ("######", "Header 6"),
        ]

        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on, strip_headers=False)
        md_header_splits = markdown_splitter.split_text(markdown_content)

        split_docs = []
        if spliter == "md":
            split_docs = md_header_splits

        if spliter == "md-txt":
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            split_docs = text_splitter.split_documents(md_header_splits)

        return split_docs


    #Replace the image URLs in the markdown file with MinIO addresses, and use HTML img tags to replace the original markdown image tags.
    def replace_and_convert_images_in_md(self, md_file_path, new_base_url):
        with open(md_file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        pattern = r'!\[(.*?)\]\((images/.*?)\)'

        def replace_and_convert(match):
            alt_text = match.group(1)
            original_path = match.group(2)
            file_name = original_path.split('/')[-1]
            new_url = f"{new_base_url}/{file_name}"
            return f'<img src="{new_url}" alt="{alt_text}">'

        new_content = re.sub(pattern, replace_and_convert, content)

        with open(md_file_path, 'w', encoding='utf-8') as file:
            file.write(new_content)

        return new_content