
# a2s server

uv run agent 


docker run --rm \
  -e "Agent_Host=192.168.3.7" \
  -e "Agent_Port=22200" \
  -e "DataServicesURL=http://192.168.3.7:22000" \
  -e "Data_Descriptor=datatunerx" \
  -e 'DescriptorTypes=[{"name":"datatunerx","descriptorType":"code","codeRepoType":"gitee","codeRepoPath":"https://gitee.com/jamesxiong888/datatunerx.git","codeRepoBranch":"main","codeRepoToken":""}]' \
  -e "DD_NAMESPACE=dac" \
  -e "Agent_Name=finetune" \
  -e "Agent_Description=I am a finetune expert." \
  -e "LANGFUSE_SECRET_KEY=sk-lf-006f7d92-b2c6-4022-9142-5630355c9633" \
  -e "LANGFUSE_PUBLIC_KEY=pk-lf-a19667ad-64d2-4133-939c-38e2c21144ba" \
  -e "LANGFUSE_BASE_URL=http://192.168.3.7:3000" \
  -p 22200:10100 \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.6.0-amd64 \
  --redis-host 192.168.3.7 \
  --redis-port 6389 \
  --redis-db 1 \
  --password 123 \
  --provider openai_compatible \
  --api-key sk-xxx \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model deepseek-v3.2 \
  --max-steps 3