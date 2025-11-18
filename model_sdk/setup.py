from setuptools import setup, find_packages

setup(
    name="model_sdk",
    version="0.1.0",
    packages=find_packages(exclude=["tests*"]),  # 排除测试目录
    install_requires=[
        "pydantic>=2.5.3",
        "requests>=2.31.0",
        "langchain>=0.3.26",
        "python-dotenv>=1.0.0",
        "langchain_community>=0.3.26",
        "setuptools>=68.0.0",
        "dashscope>=1.23.6",
        "gevent~=24.11.1",
        "tiktoken~=0.8.0",
        "psycopg2-binary~=2.9.10",
        "langchain-openai~=0.3.28",
        "openai~=1.96.1",
    ],
    python_requires=">=3.12",  # 降低Python版本要求以增加兼容性
    author="james",
    author_email="james.xiong@daocloud.io",
    description="A SDK for interacting with various AI models",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)