from setuptools import setup, find_packages
from pathlib import Path

# read the contents of the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()
setup(
    name="flow-forecaster",
    version="0.1.1",
    description="Flow Forecaster",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords="",
    url="https://github.com/pnnl/FlowForecaster",
    author="Hyungro Lee",
    author_email="hyungro.lee@pnnl.gov",
    packages=find_packages(),
    install_requires=[
        "networkx",
        "numpy",
        "matplotlib",
        "pandas",
    ],
    entry_points={
        "console_scripts": ["fforecaster=fforecaster.cli:cli"],
    },
    include_package_data=True,
    package_data={"fforecaster": ["fforecaster/data/*.json", "fforecaster/data/schema/*.json"]},
)
