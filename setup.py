"""Setup script for SkrobbleDS

To install:
    pip install -e .

To create a distribution:
    python setup.py sdist bdist_wheel
"""
from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

with open("README.md") as f:
    long_description = f.read()

setup(
    name="SkrobbleDS",
    version="0.95.3",
    description="Last.fm scrobbler for Linn DS UPnP media players",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rockfather",
    license="See Licence.txt",
    python_requires=">=3.8",
    install_requires=requirements,
    packages=find_packages(),
    py_modules=[
        "SkrobbleDs",
        "LastFm",
        "Logger",
        "Player",
        "Scrobbler",
        "Settings",
        "WebUi",
        "Database",
        "EventBus",
        "Constants"
    ],
    include_package_data=True,
    package_data={
        '': ['templates/*.html', 'favicon.png'],
    },
    entry_points={
        'console_scripts': [
            'skrobbleds=SkrobbleDs:main',
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Sound/Audio",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
