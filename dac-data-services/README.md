# Server

export DATA_SERVICES="http://192.168.3.7:22000"

uv run dac-data-services --host 192.168.3.7 --port 26000


docker run --rm \
  --name dac-data-services \
  -p 26000:8000 \
  -e DATA_SERVICES="http://192.168.3.7:22000" \
  -e DATA_DESCRIPTOR="dac_dd202601281443" \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/dac-data-services:v0.6.0-amd64



docker run --rm \
  --name dac-data-services \
  -p 26001:8000 \
  -e DATA_SERVICES="http://192.168.3.7:22000" \
  -e DATA_DESCRIPTOR="dac_dd202601281653" \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/dac-data-services:v0.6.0-amd64
