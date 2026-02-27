import hashlib
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FingerprintBuilder:
    
    def generate_fingerprint_id(self, summary: str) -> str:
        """
        Generate fingerprint ID using MD5 hash
        
        Args:
            summary: Summary text
            
        Returns:
            MD5 hash value as fingerprint ID
        """
        return hashlib.md5(summary.encode()).hexdigest()


    def generate_db_fingerprint_summary(self, data_type, tables_schema_md_list) -> str:
        """
        Generate fingerprint summary
        
        Args:
            connection_information, 
            tables_detail, 
            tables_relationship, 
            semantic_information, 
            schema_md_list
            
        Returns:
            summary text
        """

        summary = {
            "data_type": data_type,

            "tables_schema": tables_schema_md_list
        }

        summary_str = json.dumps(summary, ensure_ascii=False, indent=4)

        return summary_str
    
    def generate_code_fingerprint_summary(self, data_type, connection_info) -> str:
        """
        Generate fingerprint summary
        
        Args:
            connection_information, 
            
        Returns:
            summary text
        """

        summary = {
            "data_type": data_type,

            "connection_information": connection_info
        }

        summary_str = json.dumps(summary, ensure_ascii=False, indent=4)

        return summary_str
    
    