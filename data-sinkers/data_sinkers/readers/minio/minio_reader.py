import tempfile
import os
from typing import Any, Dict, Optional, Tuple, List
from abc import ABC, abstractmethod
from io import BytesIO
from minio.error import S3Error
from langchain.schema import Document
from .minio_conn import GeneralMinio
from ..base.base_reader import BaseDataReader
from ...file_processors.general import Processor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minio_reader")

class MinIOReader(BaseDataReader):
    def _validate_config(self) -> None:
        required_keys = ['bucket', 'host', 'access_key', 'secret_key']
        for key in required_keys:
            assert key in self.config, f"Missing {key} configuration"
    
    def _connect(self) -> Any:
        
        logger.info(f"connect to minio: {self.config['host']}, access_key={self.config['access_key']}, secret_key={self.config['secret_key']}, bucket={self.config['bucket']}")
        return GeneralMinio(
            host=self.config['host'],
            access_key=self.config['access_key'],
            secret_key=self.config['secret_key']
        )
    
    def query_one(self, object_name: str, **kwargs) -> List[Document]:
        """
        Download file from MinIO to temporary file

        Parameters:
            object_name: Object name in MinIO (including path)
            kwargs: May include additional parameters such as:
                   - bucket: Override bucket in config
                   - expires: Pre-signed URL expiration time (seconds)
        """
        result = []
        bucket = kwargs.get('bucket', self.config['bucket'])
        expires = kwargs.get('expires', 3600)  # Default 1 hour
        
        temp_path = ""
        filename = ""

        try:
            data = self.client.conn.get_object(bucket, object_name)
            file_data = data.read()
            
            filename = os.path.basename(object_name)

            suffix = os.path.splitext(filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(file_data)
                temp_path = tmp_file.name
            
            chunk_size = 1000
            splitter_type = "recursive"

            processor = Processor(
                chunk_size=chunk_size,
                chunk_overlap=chunk_size // 5,
                splitter_type=splitter_type
            )
            
            result = processor.process_file(temp_path)

            return result
            
        except S3Error as e:
            logger.error(f"MinIO error: {e}")
            return []
        except Exception as e:
            logger.error(f"file process error: {e}")
            return []
        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            logger.error(f"Error processing {temp_path}: {e}")
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    
    def query(self, prefix: str = "", recursive: bool = True, objects: Optional[List[str]] = None, **kwargs) -> List[Document]:
        """
        Read all files under bucket (supports filtering)
        
        Parameters:
            prefix: File prefix filter
            recursive: Whether to recursively process subdirectories
            objects: Specify list of objects to query, if provided only these objects will be queried
            kwargs: Additional parameters passed to query method
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents = []
        
        if objects is not None:
            # If objects parameter is provided, directly use the specified object list
            file_objects = [obj for obj in objects if not obj.endswith('/')]
            logger.info(f"Using specified {len(file_objects)} objects for processing")
        else:
            # Get all object list
            objects_list = self.client.list_objects(prefix, recursive, bucket)
            logger.info(f"Found {len(objects_list)} objects to process")

            # Filter out directories and empty files
            file_objects = [obj for obj in objects_list if not obj.endswith('/')]
            logger.info(f"Remaining {len(file_objects)} files after filtering")
        
        # Process files one by one
        for i, obj_name in enumerate(file_objects):
            logger.info(f"Processing file {i+1}/{len(file_objects)}: {obj_name}")
            
            try:
                # Call existing query method to process single file
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
                
                logger.info(f"File {obj_name} processing completed, generated {len(documents)} document segments")
                
            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue
        
        return all_documents
    
    def query_by_extension(self, extensions: List[str], prefix: str = "", recursive: bool = True, **kwargs) -> List[Document]:
        """
        Read files filtered by file extension
        
        Parameters:
            extensions: File extension list, such as ['.pdf', '.txt']
            prefix: Prefix filter
            recursive: Whether to recurse
            bucket: Specify bucket
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents = []
        
        # Get all objects
        objects = self.client.list_objects(prefix, recursive, bucket)
        
        # Filter by extension
        filtered_objects = [
            obj for obj in objects 
            if not obj.endswith('/') and any(obj.lower().endswith(ext.lower()) for ext in extensions)
        ]
        
        logger.info(f"Found {len(filtered_objects)} files matching extensions {extensions}")
        
        # Process filtered files
        for obj_name in filtered_objects:
            try:
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue
        
        return all_documents
    
    def batch_query(self, object_names: List[str], **kwargs) -> List[Document]:
        """
        Batch process specified file list
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents = []
        
        for obj_name in object_names:
            try:
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue
        
        return all_documents

    
    def close(self) -> None:
        """MinIO connection does not require special close handling"""
        pass
