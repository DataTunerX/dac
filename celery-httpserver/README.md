
test：

uv run celery-httpserver --host 192.168.xxx.xxx --port 20010

docker run --rm -p 20030:8000 -e REDIS_HOST="192.168.xxx.xxx" -e REDIS_PORT="6389" -e REDIS_DB_BROKER="2" -e REDIS_DB_BACKEND="3" -e REDIS_PASSWORD="123" registry.cn-shanghai.aliyuncs.com/jamesxiong/celery-httpserver:v0.0.1-amd64


# test case


## create dd

mysql：

```
curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "AddOrUpdate",
    "classification": [
      {
        "domain": "Science and Technology",
        "category": "Computer Science and Technology", 
        "subcategory": "Software Engineer",
        "tags": [
          {
            "skill": ["Programming", "Algorithms"]
          },
          {
            "industry": ["Internet"]
          }
        ]
      }
    ],
    "descriptor": {
      "name": "dd-101",
      "namespace": "dac"
    },
    "extract": {
      "tables": ["deposit_data","balance_sheet","loan_data","retail_loan_detail"]
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
```

## delete dd

```
curl -X POST http://192.168.xxx.xxx:20030/trigger_task \
  -H "Content-Type: application/json" \
  -d '{
  "data": {
    "operation": "Delete",
    "descriptor": {
      "name": "dd-62",
      "namespace": "dac"
    }
  }
}'
```

## get task status

```
curl http://192.168.xxx.xxx:20030/task_status/5db7f514-f966-4972-b982-73db22ef1576

```

output:

{"task_id":"343b8316-e425-418e-be6c-0f3ed0b9bb22","status":"SUCCESS","result":"{xxx}"}




## Check if the task has entered the correct queue (Redis example):

```
redis-cli LRANGE celery:dataset 2 -1
```

