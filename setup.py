"""Setup configuration for stocky-mcp package."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="stocky-mcp",
    version="1.0.0",
    author="Your Name",  # TODO: Customize this
    author_email="your.email@example.com",  # TODO: Customize this
    description="A friendly MCP server for searching royalty-free stock images",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/stocky-mcp",  # TODO: Customize this
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "mcp>=1.0.0",
        "aiohttp>=3.8.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "stocky=stocky_mcp:main",
        ],
    },
    keywords="mcp stock-images pexels unsplash royalty-free",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/stocky-mcp/issues",  # TODO: Customize this
        "Source": "https://github.com/yourusername/stocky-mcp",  # TODO: Customize this
    },
)
