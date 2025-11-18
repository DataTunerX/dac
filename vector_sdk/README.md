
# 表结构

vectorsdk=# \d embedding_test_collection 
         Table "public.embedding_test_collection"
  Column   |     Type     | Collation | Nullable | Default 
-----------+--------------+-----------+----------+---------
 id        | uuid         |           | not null | 
 text      | text         |           | not null | 
 meta      | jsonb        |           | not null | 
 embedding | vector(1024) |           | not null | 
Indexes:
    "embedding_test_collection_pkey" PRIMARY KEY, btree (id)
    "embedding_cosine_v1_idx_2f0e5d3c" hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')



# 表内容

select id, text, meta from embedding_test_collection limit 1;
                  id                  |                    text                     |                                   meta                                   
--------------------------------------+---------------------------------------------+--------------------------------------------------------------------------
 1d86ab5b-c778-4ad7-beb3-9789664db6cc | The quick brown fox jumps over the lazy dog | {"author": "John Doe", "doc_id": "1d86ab5b-c778-4ad7-beb3-9789664db6cc"}
(1 row)


# test.py 测试数据三行

select count(*) from embedding_test_collection limit 1;
 count 
-------
     3
(1 row)


