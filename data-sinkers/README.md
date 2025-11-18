# Server

## Tasks: Accept tasks that need processing, then use readers, splitters, file_processors, and analyzers to complete data processing.

## File Processors: Used to read files and split them using splitters.

## Readers: Used to read data from data sources, including MySQL, PostgreSQL, MinIO, file servers, etc. Each has its own independent implementation. If it's a file type, file_processors can be used for processing and splitting afterwards. If it's not a file type, the read data is split using splitters.

## Splitters: Used to split text, mainly as a utility component.

## Analyzers: Use large language models to analyze data and generate names for the data.

# Parameter Description

1. ENABLE_ALLINONE: disable/enable - Determines whether to treat all SQL as a single complete shard during shard generation.

2. SQL_BATCHSIZE: If ENABLE_ALLINONE is disabled, batch processing will be performed. Each batch size is defined by SQL_BATCHSIZE, meaning SQL_BATCHSIZE number of tables form one chunk. Since fingerprint generation only supports batch mode, SQL_BATCHSIZE must be set.

3. ENABLE_SAMPLE_DATA: disable/enable - Used to set sample data for each SQL shard. The sample data for each shard will only include data from the tables involved in that shard.

4. SQL_PROCESS_MODE: batch/dictionary - 
   - batch: Selects a batch number of tables at once, then uses the tables' fingerprints and schema as one chunk.
   - dictionary: Summarizes the business meaning represented by all tables, then extracts key information from each table, omitting non-business meaningful elements like field types and lengths. This is used in subsequent agents to first analyze required database tables based on overview information, then dynamically generate the schema of needed tables within the agent to improve table hit accuracy.

# Local Testing:


worker:

docker run --rm -e REDIS_HOST="192.168.xxx.xxx" -e REDIS_PORT="6389" -e REDIS_DB_BROKER="2" -e REDIS_DB_BACKEND="3" -e REDIS_PASSWORD="123" -e DATA_SERVICES="http://192.168.xxx.xxx:22000" -e PROVIDER="openai_compatible" -e API_KEY="sk-xxx" -e BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" -e Model="qwen2.5-72b-instruct" -e Temperature="0.01" -e ENABLE_ALLINONE="disable" -e "SQL_BATCHSIZE=2" -e "SQL_PROCESS_MODE=dictionary" -e ENABLE_SAMPLE_DATA="enable" -e MINERU_MODEL_SOURCE="local" -e MINERU_DEVICE_MODE="cpu" -e CELERY_WORKER_AMOUNT=10 -e CELERY_WORKER_CLASS=gevent data-sinkers:v0.2.0-amd64




# mineru cpu

export MINERU_MODEL_SOURCE=local

export MINERU_MODEL_SOURCE=modelscope

export MINERU_DEVICE_MODE="cpu"  


# test case：


## mysql

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "classification": [
      {
        "domain": "科学技术类",
        "category": "计算机科学与技术",
        "subcategory": "软件工程师",
        "tags": [
          {
            "skill": ["编程", "算法"]
          },
          {
            "industry": ["互联网"]
          }
        ]
      }
    ],
    "descriptor": {
      "name": "dd-a04",
      "namespace": "dac"
    },
    "extract": {
      "tables": [],
      "query": []
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": [
        {
          "query": "查找年龄大于30岁的用户",
          "answer": "SELECT name, age FROM users WHERE age > 30"
        },
        {
          "query": "统计最近7天注册的用户数量",
          "answer": "SELECT COUNT(name) FROM users WHERE registration_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        }
      ],
      "background_knowledge": [{"description":"年度总额采用年末值进行处理。举例来说，如果想知道2023年的贷款总额，只需要查询2023年的记录中，看看月份最大的那个月的数据就是2023年的贷款总额。"}]
    },
    "source": {
      "metadata": {
        "database": "dactest",
        "host": "192.168.xxx.xxx",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



## mysql no prompts

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-a05",
      "namespace": "dac"
    },
    "extract": {
      "tables": [],
      "query": []
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "test1",
        "host": "192.168.xxx.xxx",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



## fileserver pdf

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d01",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.pdf"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## fileserver docx

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d05",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.docx"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver excel

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d06",
      "namespace": "dac"
    },
    "extract": {
      "files": ["qa.xlsx"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver txt

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d07",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.txt"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver md

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d08",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.md"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## fileserver csv

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-d09",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.csv"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## minio pdf

curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-e01",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.pdf"]
    },
    "processing": {
      "cleaning": [
        {
          "rule": "remove_duplicates",
          "params": {
            "fields": "user_id,timestamp"
          }
        },
        {
          "rule": "fill_missing",
          "params": {
            "field": "price",
            "value": "0"
          }
        }
      ]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.xxx.xxx:9000",
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "bucket": "dactest"
      },
      "name": "minio-production",
      "type": "minio"
    }
  }
}'

