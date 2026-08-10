from setuptools import setup, find_packages

setup(
    name="skill_sdk",
    version="0.3.1",
    packages=find_packages(exclude=["tests*"]),  # 排除测试目录
    install_requires=[
        "requests==2.32.5",
        "readability-lxml>=0.8.1",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.0.0",
        "pydantic>=2.7.4",
        "PyYAML>=6.0.1",
        "python-dotenv>=1.0.0",
        "setuptools>=68.0.0",
        "dashscope>=1.23.6",
        "gevent~=24.11.1",
        "psycopg2-binary~=2.9.10",
        "langchain-classic~=1.0.0",
        "langchain>=1.0,<2",
        "langchain-core>=1.3.0,<2",
        "langchain-text-splitters>=1.0.0,<2",
        "langchain_community>=0.4,<0.5",
        "langchain-mcp-adapters>=0.0.9",
        "langchain-neo4j>=0.6.0",
        "langchain-openai>=1.0.0",
        "openai>=1.104.2",
        "pymupdf>=1.24.0",
        "python-lsp-jsonrpc==1.1.2",
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