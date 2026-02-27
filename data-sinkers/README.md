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

tasks:

docker run --rm -e REDIS_HOST="192.168.3.7" -e REDIS_PORT="6389" -e REDIS_DB_BROKER="4" -e REDIS_DB_BACKEND="5" -e REDIS_PASSWORD="123" -e DATA_SERVICES="http://192.168.3.7:22000" -e PROVIDER="openai_compatible" -e API_KEY="sk-xxx" -e BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" -e Model="deepseek-v3.2" -e Temperature="0.01" -e ENABLE_ALLINONE="disable" -e "SQL_BATCHSIZE=2" -e "SQL_PROCESS_MODE=dictionary" -e ENABLE_SAMPLE_DATA="enable" -e MINERU_MODEL_SOURCE="local" -e MINERU_DEVICE_MODE="cpu" -e CELERY_WORKER_AMOUNT=10 -e CELERY_WORKER_CLASS=gevent -e regroup_batch_size="10" -e CELERY_HTTPSERVER_API_BASE_URL="http://192.168.3.7:20050" data-sinkers:v0.6.0-arm64


job:

docker run --rm -e DATA_SERVICES="http://192.168.3.7:22000" -e PROVIDER="openai_compatible" -e API_KEY="sk-xxx" -e BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" -e Model="deepseek-v3.2" -e Temperature="0.01" -e ENABLE_ALLINONE="disable" -e "SQL_BATCHSIZE=2" -e "SQL_PROCESS_MODE=dictionary" -e ENABLE_SAMPLE_DATA="enable" -e MINERU_MODEL_SOURCE="local" -e MINERU_DEVICE_MODE="cpu"  -e regroup_batch_size="10" -e DATA_DESCRIPTOR="dac_dd202601281653" -v /Users/james/daocloud/code/dac/data-sinkers/data_sinkers/job-testdata.json:/app/data.json  -v /Users/james/daocloud/code/docker/status/status.json:/app/status/status.json data-sinkers-job:v0.6.0-arm64


status:

docker run --rm -p 8989:8000 -v /Users/james/daocloud/code/docker/status:/app/status data-sinkers-status:v0.5.0-amd64





clean data：

SET FOREIGN_KEY_CHECKS = 0;

-- 执行 TRUNCATE

TRUNCATE `fingerprint`.`dd_group_relation`;

TRUNCATE `fingerprint`.`semantic_groups`;

-- 重新启用外键检查
SET FOREIGN_KEY_CHECKS = 1;



# mineru cpu

export MINERU_MODEL_SOURCE=local

export MINERU_MODEL_SOURCE=modelscope

export MINERU_DEVICE_MODE="cpu"  



# test case：

## mysql



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "nextcloud_mysql_2",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "nextcloud",
        "host": "10.17.0.41",
        "password": "nextcloudpass",
        "port": "32012",
        "user": "nextcloud"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'





### bank

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd202601281653",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
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
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "bank2",
      "namespace": "dac"
    }
  }
}'



### user_management


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "user_management",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "user_management",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "user_management",
      "namespace": "dac"
    }
  }
}'




### product_management


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "product_management",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "product_management",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "product_management",
      "namespace": "dac"
    }
  }
}'


### order_management


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "order_management",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "order_management",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "order_management",
      "namespace": "dac"
    }
  }
}'


### library_management


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "library_management",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "library_management",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "library_management",
      "namespace": "dac"
    }
  }
}'


### corporate_hr


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "corporate_hr",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "corporate_hr",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "corporate_hr",
      "namespace": "dac"
    }
  }
}'




==================================================================



## mysql with code

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "ecommerce-system",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "codeRepo":{
      "codeRepoType": "gitee",
      "codeRepoPath": "https://gitee.com/jamesxiong888/test-code",
      "codeRepoBranch": "main",
      "codeRepoToken": ""
    },
    "source": {
      "metadata": {
        "database": "test1",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "ecommerce-system",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "test1",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



## mysql with no code

### test1

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "online-education",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "online_edu_bi_test",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'


### corporate_hr

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "org-project-management",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "database": "corporate_hr",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "corporate_hr",
      "type": "mysql"
    }
  }
}'


## mysql no prompts

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-aa01",
      "namespace": "dac"
    },
    "extract": {
      "tables": []
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "codeRepo":{
      "codeRepoType": "github",
      "codeRepoPath": "https://github.com/James-Dao/test-code",
      "codeRepoBranch": "main",
      "codeRepoToken": ""
    },
    "source": {
      "metadata": {
        "database": "test1",
        "host": "192.168.3.7",
        "password": "123",
        "port": "3307",
        "user": "root"
      },
      "name": "mysql-production",
      "type": "mysql"
    }
  }
}'



## code github

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-github-aa01",
      "namespace": "dac"
    },
    "source": {
      "metadata": {
        "codeRepoPath": "https://github.com/James-Dao/test-code",
        "codeRepoBranch": "main",
        "codeRepoToken": ""
      },
      "name": "github-production",
      "type": "github"
    }
  }
}'


curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "datatunerx",
      "namespace": "dac"
    },
    "source": {
      "metadata": {
        "codeRepoPath": "https://gitee.com/jamesxiong888/datatunerx.git",
        "codeRepoBranch": "main",
        "codeRepoToken": ""
      },
      "name": "gitee",
      "type": "gitee"
    }
  }
}'



curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-github-datatunerx",
      "namespace": "dac"
    },
    "source": {
      "metadata": {
        "codeRepoPath": "https://github.com/DataTunerX/datatunerx.git",
        "codeRepoBranch": "main",
        "codeRepoToken": ""
      },
      "name": "github-production",
      "type": "github"
    }
  }
}'




## code gitee

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-gitee-aa01",
      "namespace": "dac"
    },
    "source": {
      "metadata": {
        "codeRepoPath": "https://gitee.com/jamesxiong888/test-code.git",
        "codeRepoBranch": "main",
        "codeRepoToken": ""
      },
      "name": "gitee-production",
      "type": "gitee"
    }
  }
}'



## fileserver pdf

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## fileserver docx

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver excel

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver txt

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'




## fileserver md

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## fileserver csv

curl -X POST http://192.168.3.7:20030/trigger_task \
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
        "host": "192.168.3.7",
        "port": "8000"
      },
      "name": "fileserver-production",
      "type": "fileserver"
    }
  }
}'



## minio pdf

curl -X POST http://192.168.3.7:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "descriptor": {
      "name": "dd-minio-01",
      "namespace": "dac"
    },
    "extract": {
      "files": ["naive.pdf"]
    },
    "prompts": {
      "fewshots": null,
      "background_knowledge": null
    },
    "source": {
      "metadata": {
        "host": "192.168.3.7:9100",
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "bucket": "dactest"
      },
      "name": "minio-production",
      "type": "minio"
    }
  }
}'

