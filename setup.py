from encodings import utf_8
from typing import List

import setuptools

with open("README.md", "r", encoding=utf_8.getregentry().name) as fhand:
    long_description = fhand.read()


def get_packages_from_requierements_file() -> List[str]:
    with open("requirements.txt", "r", encoding=utf_8.getregentry().name) as f:
        contents = f.read()
    return contents.strip().split("\n")


setuptools.setup(
    name="cmlutils",
    version="1.0.0",
    author="Cloudera",
    author_email="Cloudera-support",
    description=(
        "Command line tool to enhance the Cloudera Machine Learning (CML) experience. "
        " It provides various utilities and functionalities to help working with Cloudera Machine Learning."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/cloudera/cmlutils",
    project_urls={},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=get_packages_from_requierements_file(),
    packages=setuptools.find_packages(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "cmlutil = cmlutils.cli_entrypoint:main",
        ]
    },
)
