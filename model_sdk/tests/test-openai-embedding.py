import os
from langchain_openai import OpenAIEmbeddings


openai = OpenAIEmbeddings(
			# openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
			base_url="http://10.xxx.xxx.xxx:xxx/v1",
			api_key="asd",
			# model="text-embedding-v4"
			model="bge-m3"
		)

print(openai.embed_query("hello"))