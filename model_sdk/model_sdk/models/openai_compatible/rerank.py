import json
from json import dumps
import os
import time
import logging
from enum import Enum
import requests
from requests import HTTPError, post
from yarl import URL
from typing import Optional, Dict, List, Union, Generator, Any, cast
from pydantic import Field, BaseModel
from decimal import Decimal
from urllib.parse import urljoin
from ...api.base import RerankDocument, RerankResult
from ...api.base import BaseRerank


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class OpenAICompatibleRerank(BaseRerank):
    """与您现有OpenaiCompatibleRerankModel保持一致的实现"""
    
    def __init__(
        self,
        provider: str,
        model_name: str,
        model_settings: Dict[str, Any],
    ):
        self.provider = provider
        self.model_name = model_name
        self.model_settings = model_settings
        self.api_key = model_settings.get("api_key")
        self.base_url = model_settings.get("base_url")
        
        if not self.base_url:
            raise ValueError("API Base is required")

    def invoke(
        self,
        query: str,
        docs: List[str],
        score_threshold: Optional[float] = None,
        top_n: Optional[int] = None,
        user: Optional[str] = None,
    ) -> RerankResult:
        if len(docs) == 0:
            return RerankResult(model=self.model_name, docs=[])

        url = str(URL(self.base_url) / "rerank")
        headers = {
            "Content-Type": "application/json",
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        top_n = top_n or len(docs)
        
        data = {
            "model": self.model_name,
            "query": query,
            "documents": docs,
            "top_n": top_n,
            "return_documents": True,
        }

        try:
            response = requests.post(url, headers=headers, data=dumps(data), timeout=60)
            response.raise_for_status()
            results = response.json()

            rerank_documents = []
            scores = [result["relevance_score"] for result in results["results"]]

            # Min-Max Normalization
            min_score = min(scores)
            max_score = max(scores)
            score_range = max_score - min_score if max_score != min_score else 1.0

            for result in results["results"]:
                index = result["index"]
                text = docs[index]
                document = result.get("document", {})
                
                if document:
                    if isinstance(document, dict):
                        text = document.get("text", docs[index])
                    elif isinstance(document, str):
                        text = document

                normalized_score = (result["relevance_score"] - min_score) / score_range

                if score_threshold is None or normalized_score >= score_threshold:
                    rerank_documents.append(
                        RerankDocument(
                            index=index,
                            text=text,
                            score=normalized_score,
                        )
                    )

            rerank_documents.sort(key=lambda doc: doc.score, reverse=True)
            return RerankResult(model=self.model_name, docs=rerank_documents)

        except HTTPError as e:
            logger.error(f"Rerank request failed: {e}")
            raise


    async def ainvoke(
        self,
        query: str,
        docs: List[str],
        score_threshold: Optional[float] = None,
        top_n: Optional[int] = None,
        user: Optional[str] = None,
    ) -> RerankResult:
        """异步实现（使用httpx）"""
        import httpx
        
        if len(docs) == 0:
            return RerankResult(model=self.model_name, docs=[])

        url = str(URL(self.base_url) / "rerank")
        headers = {
            "Content-Type": "application/json",
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        top_n = top_n or len(docs)
        
        data = {
            "model": self.model_name,
            "query": query,
            "documents": docs,
            "top_n": top_n,
            "return_documents": True,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data, timeout=60)
                response.raise_for_status()
                results = response.json()

                rerank_documents = []
                scores = [result["relevance_score"] for result in results["results"]]

                min_score = min(scores)
                max_score = max(scores)
                score_range = max_score - min_score if max_score != min_score else 1.0

                for result in results["results"]:
                    index = result["index"]
                    text = docs[index]
                    document = result.get("document", {})
                    
                    if document:
                        if isinstance(document, dict):
                            text = document.get("text", docs[index])
                        elif isinstance(document, str):
                            text = document

                    normalized_score = (result["relevance_score"] - min_score) / score_range

                    if score_threshold is None or normalized_score >= score_threshold:
                        rerank_documents.append(
                            RerankDocument(
                                index=index,
                                text=text,
                                score=normalized_score,
                            )
                        )

                rerank_documents.sort(key=lambda doc: doc.score, reverse=True)
                return RerankResult(model=self.model_name, docs=rerank_documents)

        except httpx.HTTPStatusError as e:
            logger.error(f"Async rerank request failed: {e}")
            raise

