import os
import time
from minio import Minio
from io import BytesIO
import logging
from typing import Any, Dict, Optional, Tuple, List
from minio.error import S3Error

minio_logger = logging.getLogger("minio")

class GeneralMinio(object):
    def __init__(self, host="localhost:9000", access_key="minioadmin", secret_key="minioadmin"):
        self.host = host
        self.access_key = access_key
        self.secret_key = secret_key
        self.conn = Minio(
            host,
            access_key=access_key,
            secret_key=secret_key,
            secure=False
        )

    def put(self, bucket, fnm, binary):
        try:
            if not self.conn.bucket_exists(bucket):
                self.conn.make_bucket(bucket)

            return self.conn.put_object(bucket, fnm, BytesIO(binary), len(binary))
        except Exception as e:
            minio_logger.error(f"Fail put {bucket}/{fnm}: {str(e)}")
            raise

    def rm(self, bucket, fnm):
        try:
            self.conn.remove_object(bucket, fnm)
        except Exception as e:
            minio_logger.error(f"Fail rm {bucket}/{fnm}: {str(e)}")

    def get(self, bucket, fnm):
        try:
            r = self.conn.get_object(bucket, fnm)
            return r.read()
        except Exception as e:
            minio_logger.error(f"fail get {bucket}/{fnm}: {str(e)}")
            return None

    def obj_exist(self, bucket, fnm):
        try:
            self.conn.stat_object(bucket, fnm)
            return True
        except Exception:
            return False

    def list_objects(self, prefix: str = "", recursive: bool = True, bucket: str = None) -> List[str]:
        objects = []
        try:
            obj_list = self.conn.list_objects(bucket, prefix=prefix, recursive=recursive)
            for obj in obj_list:
                objects.append(obj.object_name)
        except Exception as e:
            minio_logger.error(f"list object fail: {e}")
        return objects

    def list_objects_with_info(self, prefix: str = "", recursive: bool = True, bucket: str = None) -> List[Dict[str, Any]]:
        objects_info = []
        try:
            obj_list = self.conn.list_objects(bucket, prefix=prefix, recursive=recursive)
            for obj in obj_list:
                objects_info.append({
                    'object_name': obj.object_name,
                    'size': obj.size,
                    'last_modified': obj.last_modified,
                    'etag': obj.etag,
                    'is_dir': obj.is_dir
                })
        except Exception as e:
            minio_logger.error(f"list object fail: {e}")
        return objects_info

    def get_presigned_url(self, bucket, fnm, expires):
        try:
            return self.conn.get_presigned_url("GET", bucket, fnm, expires)
        except Exception as e:
            minio_logger.error(f"fail get {bucket}/{fnm}: {str(e)}")
            return None


if __name__ == "__main__":
    conn = GeneralMinio(host="localhost:9000", access_key="minioadmin", secret_key="minioadmin")
    fnm = "./testdata/11-408.jpg"
    from PIL import Image
    img = Image.open(fnm)
    buff = BytesIO()
    img.save(buff, format='JPEG')
    print(conn.put("test", "11-408.jpg", buff.getvalue()))
    bts = conn.get("test", "11-408.jpg")
    img = Image.open(BytesIO(bts))
    img.save("test.jpg")
