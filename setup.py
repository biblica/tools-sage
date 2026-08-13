from setuptools import setup, find_packages

setup(
    name="tools-sage",
    version="0.1.0",
    description="A Python CLI tool for SAGE",
    author="Biblica",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "sage=sage.cli:main",
        ],
    },
    extras_require={
        "dev": [
            "pytest>=7.0",
            "black>=22.0",
            "isort>=5.0",
            "flake8>=4.0",
        ],
    },
)
